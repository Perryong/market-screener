"""Bounded public Yahoo observations; session-aware completed candles only."""
from datetime import datetime, timezone
from functools import lru_cache
import math
from numbers import Real

from .validation import futures_unverified


def finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def validate_bars(bars, now):
    """Reject malformed, overlapping or unfinished canonical candles."""
    if not finite(now) or now < 0:
        raise ValueError('invalid observation time')
    previous = -1
    for bar in bars:
        if not isinstance(bar, dict) or any(not finite(bar.get(k)) for k in ('start','end','open','high','low','close','volume')):
            raise ValueError('candles require finite numeric OHLCV and times')
        if not 0 <= bar['start'] < bar['end'] <= now or bar['start'] < previous:
            raise ValueError('candles must be ordered, nonoverlapping and complete')
        if not 0 < bar['low'] <= min(bar['open'],bar['close']) <= max(bar['open'],bar['close']) <= bar['high'] or bar['volume'] < 0:
            raise ValueError('invalid candle prices or volume')
        previous = bar['end']


def _calendar(now):
    import exchange_calendars as xc
    year=datetime.fromtimestamp(now,timezone.utc).year
    return xc.get_calendar('XNYS', start=f'{year-3}-01-01',end=f'{year+1}-12-31')


@lru_cache(maxsize=4096)
def _verified_final_equity_half_hour(start, end):
    """Only the actual final XNYS half hour may shorten an hourly candle."""
    date=datetime.fromtimestamp(end,timezone.utc).date().isoformat()
    calendar=_calendar(end)
    if not calendar.is_session(date): return False
    opening=calendar.session_open(date).timestamp()
    closing=calendar.session_close(date).timestamp()
    return end==closing and start>=opening and (start-opening)%3600==0


def validate_interval(bars, interval):
    for bar in bars:
        duration=bar['end']-bar['start']
        if duration==interval: continue
        if interval==3600 and duration==1800 and _verified_final_equity_half_hour(bar['start'],bar['end']): continue
        raise ValueError('candle does not match supplied interval or verified session close')


def normalize_history(frame, interval, now, asset_class, calendar=None):
    """Discard an unfinished provider bar, never repair malformed observations."""
    import pandas as pd
    calendar=calendar or (_calendar(now) if asset_class=='stocks' else None)
    result=[]
    for timestamp,row in frame.iterrows():
        start=timestamp.timestamp()
        end=start+interval
        if calendar is not None:
            date=pd.Timestamp(timestamp).tz_convert('America/New_York').date().isoformat()
            if not calendar.is_session(date):
                raise ValueError('equity bar outside regular session')
            opening=calendar.session_open(date).timestamp()
            closing=calendar.session_close(date).timestamp()
            if not opening <= start < closing:
                raise ValueError('equity bar outside regular session')
            end=min(end,closing)
        if end > now:
            continue
        if any(not finite(row.get(key)) for key in ('Open','High','Low','Close','Volume')):
            raise ValueError('raw provider OHLCV must be finite numeric values, not booleans')
        result.append(dict(start=start,end=end,open=float(row['Open']),high=float(row['High']),low=float(row['Low']),close=float(row['Close']),volume=float(row['Volume'])))
    validate_bars(result,now)
    validate_interval(result,interval)
    return result


def collect_symbol(symbol, asset_class, now):
    """Fetch one public instrument. Failures stay explicit; no timestamp synthesis."""
    if asset_class not in ('stocks','crypto','commodities'):
        raise ValueError('unsupported asset class')
    if not isinstance(symbol,str) or not symbol or len(symbol)>40 or not finite(now) or now < 0:
        raise ValueError('invalid symbol or observation time')
    out=dict(symbol=symbol,asset_class=asset_class,source='yahoo',currency=None,
             contract_kind='continuous_future_unverified' if asset_class=='commodities' else 'spot' if asset_class=='crypto' else 'equity',
             bars_1h=[],bars_15m=[],quote=None,market_open=False,errors=[])
    try:
        import yfinance as yf
        import pandas as pd
        ticker=yf.Ticker(symbol)
        calendar=_calendar(now) if asset_class=='stocks' else None
        out['market_open']=bool(asset_class=='crypto' or (calendar is not None and calendar.is_open_on_minute(pd.Timestamp(now,unit='s',tz='UTC').floor('min'))))
        for key,interval,period,seconds in [('bars_1h','1h','2y',3600),('bars_15m','15m','60d',900)]:
            try:
                window=dict(start=int(now)-729*86400,end=int(now)) if interval=='1h' else dict(period=period)
                frame=ticker.history(**window,interval=interval,auto_adjust=False,prepost=False,timeout=8,raise_errors=True)
                out[key]=normalize_history(frame,seconds,now,asset_class,calendar)
                if not out[key]: out['errors'].append(f'{interval}: no completed bars')
            except Exception as exc:
                out['errors'].append(f'{interval}: {type(exc).__name__}: {exc}')
        # get_info has unbounded internal calls; history metadata is already fetched.
        # Inspect already-fetched metadata: getter can trigger an unbounded extra fetch.
        metadata=getattr(getattr(ticker,'_price_history',None),'_history_metadata',None) or {}
        out['currency']=metadata.get('currency')
        price=metadata.get('regularMarketPrice'); observed=metadata.get('regularMarketTime')
        if isinstance(observed,datetime) and observed.tzinfo is not None:
            observed=observed.timestamp()
        if finite(price) and price>0 and finite(observed) and 0<observed<=now:
            out['quote']=dict(price=float(price),time=float(observed),bid=None,ask=None)
        else:
            out['errors'].append('quote: missing actual regularMarketTime/price')
        if futures_unverified(asset_class,symbol):
            out['errors'].append('continuous futures: dated contract, roll, point value and market session unverified')
    except Exception as exc:
        out['errors'].append(f'collector: {type(exc).__name__}: {exc}')
    return out
