"""Public research snapshots, separate from strategy and broker data."""
import json
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit

from .shared import DataError, json_text


def finite(value):
    try:
        number = float(value) if value is not None and not isinstance(value, bool) else float('nan')
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def safe_url(value):
    try:
        parts = urlsplit(str(value or ''))
        return str(value) if parts.scheme in ('https', 'http') and parts.hostname and not parts.username else ''
    except ValueError:
        return ''


def load_settings(path, stock_symbols):
    settings = dict(stocks=list(stock_symbols), funds='SPY QQQ VOO IVV VTI ITOT SCHB QQQM SCHD VYM DGRO BND AGG TLT GLD USO VXUS VEA VWO IWM'.split(),
                    europe='ASML.AS SAP.DE SIE.DE ALV.DE AIR.PA MC.PA OR.PA TTE.PA SAN.PA BNP.PA HSBA.L AZN.L SHEL.L ULVR.L RIO.L NOVN.SW NESN.SW UBSG.SW NOVO-B.CO VOLV-B.ST'.split(),
                    proxies='SPY QQQ DIA IWM TLT USO GLD XLK XLF XLE XLV XLI XLU XLP XLY XLB XLRE XLC ^STOXX ^STOXX50E ^FTSE ^FTMC ^GDAXI ^FCHI ^AEX ^IBEX FTSEMIB.MI ^SSMI ^OMX ^OMXC25 ^OMXH25 ^BFX ^ATX PSI20.LS ^ISEQ EURUSD=X GBPUSD=X EURGBP=X EURCHF=X EURSEK=X EURNOK=X EURDKK=X'.split(),
                    max_instruments=200, max_requests=500, max_seconds=600, discovery=False,
                    api_sources=False, xbrl_entities={'ASML.AS':'724500Y6DUVHQD6OXN27'},
                    feeds=[dict(name='CNBC Markets',url='https://www.cnbc.com/id/100003114/device/rss/rss.html',category='Markets'),
                           dict(name='CNBC Technology',url='https://www.cnbc.com/id/19854910/device/rss/rss.html',category='Tech & AI'),
                           dict(name='Federal Reserve',url='https://www.federalreserve.gov/feeds/press_all.xml',category='Economy'),
                           dict(name='Federal Reserve Speeches',url='https://www.federalreserve.gov/feeds/speeches.xml',category='Economy',longform=True)])
    supplied={}
    if path and Path(path).exists():
        supplied = json.loads(Path(path).read_text())
        if not isinstance(supplied, dict) or set(supplied)-set(settings):
            raise DataError('Unknown research settings')
        settings.update(supplied)
    for key in ('stocks','funds','europe','proxies'):
        values = settings[key]
        if not isinstance(values,list) or len(set(values)) != len(values) or any(
                not isinstance(s,str) or not re.fullmatch(r'[A-Z^][A-Z0-9.^=-]{0,24}',s) for s in values):
            raise DataError('Invalid or duplicate research symbols')
    for key in ('max_instruments','max_requests','max_seconds'):
        if type(settings[key]) is not int or not 1 <= settings[key] <= 10000:
            raise DataError('Research limits must be positive integers up to 10000')
    if 'xbrl_entities' not in supplied:
        settings['xbrl_entities']={symbol:lei for symbol,lei in settings['xbrl_entities'].items() if symbol in settings['europe']}
    if type(settings['api_sources']) is not bool or not isinstance(settings['xbrl_entities'],dict) or any(
            symbol not in settings['europe'] or not isinstance(lei,str) or not re.fullmatch(r'[A-Z0-9]{20}',lei)
            for symbol,lei in settings['xbrl_entities'].items()):
        raise DataError('API sources require explicit European ticker-to-LEI mappings')
    if type(settings['discovery']) is not bool or not isinstance(settings['feeds'],list):
        raise DataError('Invalid discovery or feeds setting')
    for feed in settings['feeds']:
        if not isinstance(feed,dict) or not isinstance(feed.get('name'),str) or not safe_url(feed.get('url')):
            raise DataError('Feeds require a name and HTTP(S) URL')
    return settings


def cached_resource(store, key, ttl, now, loader, force=False):
    saved = store.get('research-cache:'+key)
    if not force and saved and now-saved['fetched_at'] < ttl and saved['data'] is not None and not saved.get('error'):
        return dict(saved,status='ok',error='')
    if not force and saved and now-saved.get('attempted_at',0) < 900 and saved.get('error') and 'budget' not in saved['error']:
        return saved
    try:
        data = loader()
        json_text(data)  # Reject nonfinite values before persistence.
        result = dict(id=key,data=data,source=key.split(':')[0],fetched_at=now,
                      attempted_at=now,observation_at=None,status='ok',error='')
    except Exception as exc:
        result = dict(saved or dict(id=key,data=None,source=key.split(':')[0],fetched_at=0,observation_at=None),
                      attempted_at=now,status='stale' if saved and saved.get('data') is not None else 'unavailable',
                      error=str(exc)[:160] if isinstance(exc,DataError) else 'Provider unavailable or invalid response')
    store.put('research-cache:'+key,result)
    return result


def empty_snapshot(mode, now):
    return dict(version=1,mode=mode,generated_at=now,instruments=[],economy=[],releases=[],ipos=[],news=[],resources=[])


def ratio(numerator, denominator):
    n, d = finite(numerator), finite(denominator)
    return n/d if n is not None and d is not None and d > 0 else None


def returns(history, as_of):
    rows = sorted((r for r in history if r['date'] <= as_of and (finite(r['close']) or 0)>0),key=lambda r:r['date'])
    result = {key:None for key in ('day','week','month','ytd','year','annualized','volatility','drawdown')}
    if len(rows)<2:
        return result
    last = rows[-1]
    end = date.fromisoformat(last['date'])
    change = lambda row: last['close']/row['close']-1
    result['day'] = change(rows[-2])
    for key, boundary in [('week',end-timedelta(days=7)),('month',end-timedelta(days=30)),
                          ('year',end-timedelta(days=365)),('ytd',date(end.year,1,1)-timedelta(days=1))]:
        previous = [r for r in rows if r['date']<=boundary.isoformat()]
        if previous:
            result[key] = change(previous[-1])
    days = (end-date.fromisoformat(rows[0]['date'])).days
    if days>=365:
        result['annualized'] = (last['close']/rows[0]['close'])**(365.25/days)-1
    peak = rows[0]['close']
    result['drawdown'] = 0
    for row in rows:
        peak = max(peak,row['close'])
        result['drawdown'] = min(result['drawdown'],row['close']/peak-1)
    monthly = {}
    for row in rows:
        if row['date'][:7] < end.isoformat()[:7]:
            monthly[row['date'][:7]]=row['close']
    closes = list(monthly.values())
    if len(closes)>=13:
        import statistics
        result['volatility']=statistics.stdev([b/a-1 for a,b in zip(closes,closes[1:])])*math.sqrt(12)
    return result


def refresh(store, settings, now):
    from . import research_sources as sources
    snapshot = empty_snapshot('live',now)
    budget=dict(remaining=settings['max_requests'],deadline=time.monotonic()+settings['max_seconds'])
    blocked, resource_map = {}, {}
    previous = store.get('research-snapshot',{})
    previous_instruments = {r['symbol']:r for r in previous.get('instruments',[])}
    def load(key, ttl, loader, network_counted=False):
        def bounded():
            provider = key.split(':')[0]
            if budget['remaining']<=0 or time.monotonic()>=budget['deadline']:
                raise DataError('Research refresh budget reached; increase research.json limits or reuse cache')
            if blocked.get(provider,0)>=3:
                raise DataError('Provider paused after repeated rate limits')
            if not network_counted:
                budget['remaining']-=1
            try:
                return loader()
            except Exception as exc:
                if '429' in str(exc) or 'rate limit' in str(exc).lower() or 'ratelimit' in type(exc).__name__.lower():
                    blocked[provider]=blocked.get(provider,0)+1
                raise DataError('Rate limit or source unavailable' if blocked.get(provider) else 'Source unavailable or invalid data') from None
        saved=store.get('research-cache:'+key,{})
        retry=settings.get('_force',False) and bool(saved.get('error')) and key not in resource_map
        resource = cached_resource(store,key,ttl,now,bounded,retry)
        resource_map[key]={k:v for k,v in resource.items() if k!='data'}
        return resource['data']
    runtime_settings = dict(settings,_load=load)
    symbols = list(dict.fromkeys(settings['stocks']+settings['funds']+settings['europe']+settings['proxies']))
    # Reserve operations for macro/calendars/news so large equity baskets cannot starve them.
    for name, loader in [('economy',sources.collect_economy),('releases',sources.collect_releases),
                         ('ipos',sources.collect_ipos),('news',sources.collect_news)]:
        try:
            snapshot[name]=loader(runtime_settings,now)
        except Exception:
            snapshot[name]=previous.get(name,[])
            snapshot['resources'].append(dict(id=name,source=name,status='stale' if snapshot[name] else 'unavailable',
                                             fetched_at=previous.get('generated_at',0),observation_at=None,error='Collection unavailable'))
    if settings['discovery']:
        import yfinance as yf
        discovered=load('Yahoo:discovery',86400,lambda: sources.discover(yf)) or []
        symbols=list(dict.fromkeys(symbols+discovered))
    supplemental=None
    if settings.get('api_sources'):
        from . import api_sources
        supplemental=api_sources.collect(dict(runtime_settings,_budget=budget,
            _load=lambda key,ttl,loader:load(key,ttl,loader,network_counted=True)),now)
    selected=symbols[:settings['max_instruments']]
    for symbol in selected:
        record=sources.collect_instrument(symbol,dict(runtime_settings,_core_only=True),now)
        if record.get('price') is None and symbol in previous_instruments:
            record=previous_instruments[symbol]
        snapshot['instruments'].append(record)
    for i,symbol in enumerate(selected):
        if budget['remaining']<=0 or time.monotonic()>=budget['deadline']:
            for field in ('financials','filings','holdings','holdings_as_of','calendar','distributions'):
                snapshot['instruments'][i][field]=previous_instruments.get(symbol,{}).get(field,snapshot['instruments'][i].get(field))
            continue
        snapshot['instruments'][i]=sources.collect_instrument(symbol,runtime_settings,now)
    if settings.get('api_sources'):
        api_sources.merge(snapshot,supplemental)
    snapshot['resources']+=list(resource_map.values())
    if not os.environ.get('SEC_USER_AGENT','').strip():
        snapshot['resources'].append(dict(id='SEC:configuration',source='SEC EDGAR',fetched_at=0,observation_at=None,status='unavailable',error='Set private SEC_USER_AGENT identification to collect SEC facts and filings'))
    snapshot['request_count']=settings['max_requests']-budget['remaining']
    snapshot['coverage']=dict(stocks=len(settings['stocks']),funds=len(settings['funds']),europe=len(settings['europe']),
                              loaded=len(snapshot['instruments']),limit=settings['max_instruments'])
    if settings.get('api_sources'):
        api_sources.connection_status(snapshot)
    store.put('research-snapshot',snapshot)
    return snapshot


def demo_snapshot(now):
    """Deterministic synthetic records, isolated from live sources and state."""
    settings=load_settings(None,['AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','JPM','BAC','GS','XOM','LLY'])
    snapshot=empty_snapshot('demo',now)
    end=datetime.fromtimestamp(now,ZoneInfo('Asia/Singapore')).date()-timedelta(days=1)
    days=[end-timedelta(days=i) for i in range(1900) if (end-timedelta(days=i)).weekday()<5][::-1]
    names={'AAPL':'Apple Inc.','MSFT':'Microsoft Corporation','NVDA':'NVIDIA Corporation','AMZN':'Amazon.com, Inc.',
           'GOOGL':'Alphabet Inc.','META':'Meta Platforms, Inc.','TSLA':'Tesla, Inc.','JPM':'JPMorgan Chase & Co.',
           'BAC':'Bank of America','GS':'Goldman Sachs','XOM':'Exxon Mobil','LLY':'Eli Lilly',
           'SPY':'SPDR S&P 500 ETF','QQQ':'Invesco QQQ Trust','VOO':'Vanguard S&P 500 ETF','IVV':'iShares Core S&P 500 ETF',
           'VTI':'Vanguard Total Stock Market ETF','SCHD':'Schwab US Dividend Equity ETF','BND':'Vanguard Total Bond Market ETF',
           'ASML.AS':'ASML Holding','SAP.DE':'SAP SE','SIE.DE':'Siemens AG','MC.PA':'LVMH',
           '^FTSE':'FTSE 100','^GDAXI':'DAX','^FCHI':'CAC 40','^STOXX':'STOXX Europe 600','^STOXX50E':'Euro Stoxx 50'}
    sectors=['Technology','Financial Services','Healthcare','Energy','Industrials','Consumer Cyclical']
    symbols=list(dict.fromkeys(settings['stocks']+settings['funds']+settings['europe'][:8]+settings['proxies']))
    for i,symbol in enumerate(symbols):
        kind='fund' if symbol in settings['funds'] else 'proxy' if symbol in settings['proxies'] else 'stock'
        region='EU' if symbol in settings['europe'] or symbol.startswith('^') or '=X' in symbol else 'US'
        currency='EUR' if region=='EU' else 'USD'
        if symbol.endswith('=X'):
            currency=symbol[3:6]
        hist=[]
        for j,day in enumerate(days):
            value=(60+i*9)*(1+j*.0002)*(1+.05*math.sin(j/24+i)+.025*math.sin(j/7+i/2))
            if '=X' in symbol:
                value=1.1+.03*math.sin(j/80+i)
            hist.append(dict(date=day.isoformat(),close=round(value,4),price=round(value,4),volume=2000000+i*20000,
                             dividend=0.35 if j%63==0 else 0,split=0))
        m=returns(hist,end.isoformat())
        m.update(market_cap=(i+2)*3.5e10,pe=None if i%7==0 else 12+i%35,pb=2+i%10,revenue_growth=.08+(i%9)*.03,
                 earnings_growth=.04+(i%8)*.035,operating_margin=.12+i%6*.035,net_margin=.07+i%6*.035,
                 roe=.1+i%7*.04,debt_equity=.2+i%5*.2,dividend_yield=.01+i%5*.004,assets=1e10*(i+1),
                 expense=.0003+i%4*.0004,cash=4e10,debt=2e10,current_ratio=2.3,revenue=2e10+i*1e9,fcf_margin=.15+i%6*.04,
                 relative_volume=.8+i%7*.2,dollar_volume=hist[-1]['price']*hist[-1]['volume'],
                 above50=i%3!=0,above200=i%4!=0,new_high=i%9==0,new_low=i%11==0)
        holdings=[dict(symbol='AAPL',name='Apple Inc.',weight=.08),dict(symbol='MSFT',name='Microsoft',weight=.07),dict(symbol='NVDA',name='NVIDIA',weight=.06)] if kind=='fund' else []
        financials=[]
        if kind=='stock':
            for year in range(end.year-5,end.year):
                for metric,factor in [('Total Revenue',1),('Free Cash Flow',.25),('Net Income',.15)]:
                    financials.append(dict(metric=metric,value=m['revenue']*.85**(end.year-year)*factor,end=f'{year}-12-31',unit=currency,source='Synthetic demonstration'))
        record=dict(symbol=symbol,name=names.get(symbol,symbol+' / synthetic research example'),region=region,kind=kind,
                    quote_type='ETF' if kind=='fund' else 'EQUITY',country='United States' if region=='US' else 'Germany' if '.DE' in symbol else 'France',
                    sector=sectors[i%len(sectors)],currency=currency,price=hist[-1]['price'],as_of=end.isoformat(),metrics=m,
                    history=hist,family='Vanguard' if symbol.startswith('V') else 'iShares' if symbol in ('IVV','AGG') else 'Invesco' if symbol.startswith('QQQ') else 'State Street',
                    category='Equity ETF' if kind=='fund' else '',description='Synthetic example used to demonstrate the research tools. All values on this page are fabricated.',
                    holdings=holdings,holdings_as_of=None,financials=financials,filings=[dict(form='10-K',date=end.isoformat(),url='https://www.sec.gov/edgar/search/')] if kind=='stock' else [],
                    distributions=[dict(date=(end-timedelta(days=7)).isoformat(),amount=.35,currency=currency)],
                    calendar=[dict(type='earnings',date=(end+timedelta(days=1+i%16)).isoformat(),status='synthetic estimate',symbol=symbol,sector=sectors[i%len(sectors)]),
                              dict(type='dividends',date=(end+timedelta(days=2+i%14)).isoformat(),status='synthetic example',symbol=symbol,currency=currency,amount=.35,payment_date=(end+timedelta(days=25)).isoformat())],
                    source='Synthetic demonstration / no real market data')
        snapshot['instruments'].append(record)
    from .research_sources import MACRO
    for i,(symbol,name,unit,transform) in enumerate(MACRO):
        history=[dict(date=(end-timedelta(days=30*j)).isoformat(),value=3+i*.3+math.sin(j/6)*.3) for j in range(60)][::-1]
        snapshot['economy'].append(dict(id=symbol,name=name,unit=unit,transform=transform,history=history,value=history[-1]['value'],previous=history[-2]['value'],date=end.isoformat(),source='Synthetic demonstration',url='https://fred.stlouisfed.org/series/'+symbol))
    snapshot['releases']=[dict(date=(end+timedelta(days=j+1)).isoformat(),name=name,time='08:30',timezone='America/New_York',source='Synthetic example',url='https://www.bls.gov/schedule/') for j,name in enumerate(['Employment report','Consumer price index','GDP estimate','Retail sales'])]
    snapshot['ipos']=[dict(name='Example '+stage+' company',symbol='DEMO'+str(i),status=stage,date=(end+timedelta(days=i)).isoformat(),price='$15 – $18',shares='10,000,000',amount='$180M',exchange='Example exchange',source='Synthetic demonstration',url='https://www.nasdaq.com/market-activity/ipos') for i,stage in enumerate(['expected','priced','filed','withdrawn'])]
    titles=['Inside the numbers: how company margins work','A closer look at the cost of owning an ETF','What to watch in the upcoming earnings calendar','Understanding the gap between short and long-term yields','Reading a fund’s holdings without losing the bigger picture','Why sector moves can tell different stories']
    snapshot['news']=[dict(id=str(i),title=title,excerpt='Synthetic editorial example. This card demonstrates publisher attribution, search, related tickers and article detail. It makes no claim about real events.',publisher='Demo Research Desk',category=['Companies','Funds','Markets','Economy'][i%4],published=datetime.fromtimestamp(now-i*7200,ZoneInfo('Asia/Singapore')).isoformat(),url='https://www.sec.gov/investor',tickers=['AAPL','SPY'] if i%2==0 else ['MSFT'],longform=i in (0,1,4)) for i,title in enumerate(titles)]
    snapshot['resources']=[dict(id='Synthetic:demo',source='Synthetic demonstration',status='ok',fetched_at=now,observation_at=end.isoformat(),error='')]
    return snapshot
