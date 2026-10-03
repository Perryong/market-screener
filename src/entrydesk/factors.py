"""Validated candle adapter for pinned Astra pure factors (AGPL-3.0)."""
from .data import finite, validate_bars, validate_interval
from .astra.calculations import compute_macd_factors, compute_rsi_factors, compute_vwap_volume_profile, compute_depth_factors
from .astra.scoring import score_composite_alpha


def validate_quote(action, entry, target, stop):
    """Strict directional geometry and gross reward/risk >= 2, no overrides."""
    if any(not finite(v) or v<=0 for v in (entry,target,stop)):
        return False, 'prices must be positive finite numbers', None
    if action=='BUY_LONG' and stop<entry<target:
        rr=(target-entry)/(entry-stop)
    elif action=='SELL_SHORT' and target<entry<stop:
        rr=(entry-target)/(stop-entry)
    else:
        return False, 'invalid directional price geometry', None
    if not finite(rr):
        return False, 'reward/risk must be finite', None
    return rr>=2, None if rr>=2 else 'reward/risk below 2', rr


def _atr_adx(bars, period=14):
    if len(bars)<period+1: return None,None
    tr=[]; plus=[]; minus=[]
    for previous,current in zip(bars,bars[1:]):
        tr.append(max(current['high']-current['low'],abs(current['high']-previous['close']),abs(current['low']-previous['close'])))
        up=current['high']-previous['high']; down=previous['low']-current['low']
        plus.append(up if up>down and up>0 else 0)
        minus.append(down if down>up and down>0 else 0)
    atr=sum(tr[:period])/period; p=sum(plus[:period])/period; m=sum(minus[:period])/period
    dx=[]
    for i in range(period-1,len(tr)):
        if i>=period:
            atr=(atr*(period-1)+tr[i])/period
            p=(p*(period-1)+plus[i])/period; m=(m*(period-1)+minus[i])/period
        dx.append(100*abs(p-m)/(p+m) if p+m else 0)
    adx=None
    if len(dx)>=period:
        adx=sum(dx[:period])/period
        for value in dx[period:]: adx=(adx*(period-1)+value)/period
    return atr,adx


def _depth(micro, price):
    out=compute_depth_factors(None,price)
    out.update(available=False,reason='depth unavailable')
    if not isinstance(micro,dict): return out
    bids=micro.get('bids'); asks=micro.get('asks')
    try:
        if not bids or not asks or any(not isinstance(row,(list,tuple)) or len(row)<2 or any(not finite(v) or v<=0 for v in row[:2]) or (len(row)>3 and (not finite(row[3]) or row[3]<0 or row[3]!=int(row[3]))) for row in list(bids)+list(asks)):
            return out
        if any(a[0]<=b[0] for a,b in zip(bids,bids[1:])) or any(a[0]>=b[0] for a,b in zip(asks,asks[1:])):
            out['reason']='unsorted or duplicate depth'; return out
        if bids[0][0]>=asks[0][0]:
            out['reason']='crossed depth'; return out
        out=compute_depth_factors(micro,price)
        out.update(available=out['depth_reliable'],reason=None if out['depth_reliable'] else out['depth_note'])
        if not out['depth_reliable']:
            out['obi_pct']=None
            out['obi_robust_pct']=None
        return out
    except (TypeError,ValueError,OverflowError): return out


def build_factors(bars_1h, bars_15m, micro=None):
    """Canonical chronological 1h/15m candles; missing tiers remain unavailable."""
    for bars,interval in ((bars_1h,3600),(bars_15m,900)):
        validate_bars(bars,max((b['end'] for b in bars if isinstance(b,dict) and finite(b.get('end'))),default=0))
        validate_interval(bars,interval)
    closes=[b['close'] for b in bars_1h]; price=closes[-1] if closes else 0
    atr,adx=_atr_adx(bars_1h)
    trend='BULL' if adx is not None and adx>=22 and len(closes)>1 and closes[-1]>closes[-15] else 'BEAR' if adx is not None and adx>=22 else 'RANGE'
    tm=compute_macd_factors(closes,price)
    tm.update(compute_rsi_factors(closes,[b['close'] for b in bars_15m],trend))
    tm.update(adx_1h=adx,rsi_14=tm['rsi_1h'])
    raw=[[b['start']*1000,b['open'],b['high'],b['low'],b['close'],b['volume']] for b in reversed(bars_15m)]
    try:
        vp=compute_vwap_volume_profile(raw,price)
    except ArithmeticError as exc:
        raise ValueError('volume profile arithmetic overflow') from exc
    window=bars_15m[-96:]
    vp['vwap']=vp.pop('vwap_24h')
    vp.update(interval_seconds=900,window_bars=len(window),window_elapsed_seconds=window[-1]['end']-window[0]['start'] if window else None,window_label=f'{len(window)} completed 15m bars',available=vp['vwap'] is not None)
    if vp['vpvr_poc']==0 and vp['vwap'] is not None: vp['vpvr_poc']=vp['vwap']
    ms=_depth(micro,price)
    out=dict(trend_momentum=tm,volatility_channel=dict(atr=atr,atr_1h=atr,atr_1h_pct=100*atr/price if atr is not None and price else None),
             volume_profile=vp,microstructure=ms,volume_money_flow=dict(available=False,cvd_1h_usd=None,taker_buy_sell_ratio=None),smart_money_derivatives=dict(available=False,reason='public candles do not contain derivatives observations'))
    out['coverage']=dict(available=['candle_momentum'] if closes else [],unavailable=['derivatives','orderflow','options','basis']+([] if ms['available'] else ['depth'])+([] if vp['available'] else ['volume_profile']))
    # Reject arithmetic overflow rather than publishing NaN/Infinity evidence.
    for block in out.values():
        if isinstance(block,dict) and any(isinstance(value,(int,float)) and not isinstance(value,bool) and not finite(value) for value in block.values()):
            raise ValueError('nonfinite computed factor')
    score_composite_alpha(out)
    return out
