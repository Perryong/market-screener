"""Optional public research APIs. Never promotes observations into trade signals."""
import copy
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urljoin, urlsplit

from .research import finite, cached_resource, empty_snapshot
from .research_sources import read_text
from .shared import DataError, timestamp

_budget = ContextVar('public_api_budget', default=None)


def read_document(url, headers=None):
    budget=_budget.get()
    if budget is not None:
        if budget['remaining']<=0 or time.monotonic()>=budget['deadline']:
            raise DataError('API network request budget reached')
        budget['remaining']-=1
    if urlsplit(url).hostname in ('www.sec.gov','data.sec.gov'):
        time.sleep(.2)  # Below SEC's 10 requests/second fair-access ceiling.
    return read_text(url,headers)


def credential(name):
    value = os.environ.get(name, '').strip()
    return value if value and not value.lower().startswith(('your_', 'replace', 'example')) else ''


def request(url, params=None, headers=None):
    # Response bodies and URLs can contain credentials. Never propagate raw errors.
    try:
        return json.loads(read_document(url + ('?' + urlencode(params) if params else ''), headers))
    except DataError:
        raise
    except Exception:
        raise DataError('API unavailable or invalid response; check coverage and credentials') from None


def kraken_rows(payload):
    if payload.get('error'):
        raise DataError('Kraken rejected the public market request')
    rows = []
    for symbol, raw in payload.get('result', {}).items():
        price, bid, ask = (finite(raw[k][0]) for k in ('c', 'b', 'a'))
        if price is None or bid is None or ask is None or not 0 < bid <= ask or price <= 0:
            raise DataError('Invalid Kraken price or spread')
        rows.append(dict(symbol={'XXBTZUSD':'BTC/USD','XETHZUSD':'ETH/USD'}.get(symbol,symbol),
                         venue_symbol=symbol, price=price,bid=bid,ask=ask,currency='USD',
                         observed_at=None,source='Kraken spot',execution_eligible=False,
                         note='REST ticker has no quote timestamp; research observation only'))
    if not rows:
        raise DataError('Kraken returned no quotes')
    return rows


def valid_time(value, now):
    try:
        return isinstance(value,str) and 0 < timestamp(value) <= now
    except (TypeError,ValueError,OverflowError):
        return False


def alpaca_quotes(payload, now):
    rows=[]
    for symbol, raw in payload.get('quotes',{}).items():
        bid,ask=finite(raw.get('bp')),finite(raw.get('ap'))
        if bid is None or ask is None or not 0 < bid <= ask or not valid_time(raw.get('t'),now):
            continue
        rows.append(dict(symbol=symbol,price=(bid+ask)/2,bid=bid,ask=ask,currency='USD',
                         observed_at=raw['t'],source='Alpaca IEX',execution_eligible=False,
                         note='IEX venue only; midpoint observation, not a consolidated executable price'))
    return rows


def coingecko_rows(payload, now):
    if not isinstance(payload,list):
        raise DataError('CoinGecko market response unavailable')
    rows=[]
    for raw in payload:
        price=finite(raw.get('current_price'))
        if price is None or price<=0 or not valid_time(raw.get('last_updated'),now):
            continue
        change=finite(raw.get('price_change_percentage_24h'))
        rows.append(dict(id=raw['id'],symbol=raw['symbol'].upper(),name=raw.get('name',raw['id']),price=price,
                         currency='USD',market_cap=finite(raw.get('market_cap')),volume=finite(raw.get('total_volume')),
                         change=change/100 if change is not None else None,observed_at=raw['last_updated'],
                         source='CoinGecko',execution_eligible=False))
    return rows


def bls_series(payload, series):
    if payload.get('status')!='REQUEST_SUCCEEDED':
        raise DataError('BLS returned no usable series')
    values={}
    for item in payload.get('Results',{}).get('series',[]):
        if item.get('seriesID') != series:
            continue
        for raw in item.get('data',[]):
            if re.fullmatch(r'M(0[1-9]|1[0-2])',raw.get('period','')) and re.fullmatch(r'\d{4}',raw.get('year','')):
                values[raw['year']+'-'+raw['period'][1:]+'-01']=finite(raw.get('value'))
    return [dict(date=date,value=value) for date,value in sorted(values.items())]


def eia_series(payload, series):
    values={}
    for raw in payload.get('response',{}).get('data',[]):
        if raw.get('series')==series and re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw.get('period','')):
            values[raw['period']]=finite(raw.get('value'))
    return [dict(date=date,value=value) for date,value in sorted(values.items())]


def xbrl_facts(payload, url, filed, expected_lei=None):
    rows={}
    for fact in payload.get('facts',{}).values():
        d=fact.get('dimensions',{})
        # Consolidated facts only. Segment axes cannot be added to entity totals.
        if set(d)-{'concept','entity','period','unit','language'}:
            continue
        if expected_lei and d.get('entity','').rsplit(':',1)[-1]!=expected_lei:
            raise DataError('XBRL fact entity does not match configured LEI')
        value=finite(fact.get('value'))
        if value is None or 'unit' not in d:
            continue
        try:
            periods=d['period'].split('/')
            end=(datetime.fromisoformat(periods[-1])-timedelta(days=1)).date().isoformat()
            start=datetime.fromisoformat(periods[0]).date().isoformat() if len(periods)==2 else None
            if len(periods)>2 or (start and start>end):
                continue
        except (KeyError,TypeError,ValueError):
            continue
        concept=d.get('concept','')
        if not concept or end>str(filed)[:10]:
            continue
        key=(concept,start,end,d['unit'],d.get('entity'))
        row=dict(metric=concept.split(':')[-1],concept=concept,value=value,start=start,end=end,
                 unit=d['unit'].removeprefix('iso4217:'),source='European XBRL',filed=filed,url=url)
        # Conflicting duplicate facts must not be chosen arbitrarily.
        if key in rows and rows[key] != row:
            rows[key]=None
        else:
            rows[key]=row
    return [row for row in rows.values() if row is not None]


def nport_holdings(text, series):
    root=ET.fromstring(text)
    ns='{http://www.sec.gov/edgar/nport}'
    def field(node,name):
        return node.findtext('.//'+ns+name)
    if field(root,'seriesId')!=series:
        raise DataError('N-PORT series does not match requested fund')
    as_of=field(root,'repPdDate')
    if not as_of or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',as_of):
        raise DataError('Missing N-PORT reporting date')
    holdings=[]
    for row in root.findall('.//'+ns+'invstOrSec'):
        weight=finite(field(row,'pctVal'))
        if weight is None:
            continue
        ticker=row.find('.//'+ns+'identifiers/'+ns+'ticker')
        cusip=field(row,'cusip')
        symbol=ticker.get('value') if ticker is not None else None
        holdings.append(dict(symbol=symbol or ('CUSIP:'+cusip if cusip else 'UNMAPPED'),name=field(row,'name') or symbol or 'Unknown',
                             weight=weight/100,asset_category=field(row,'assetCat'),source='SEC N-PORT'))
    if not holdings:
        raise DataError('N-PORT holdings missing')
    return dict(as_of=as_of,holdings=holdings,series=series)


def xbrl_url(path):
    url=urljoin('https://filings.xbrl.org/',path or '')
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.netloc!='filings.xbrl.org':
        raise DataError('Unexpected XBRL document host')
    return url


def collect_xbrl(settings, now):
    results={}
    for symbol,lei in settings.get('xbrl_entities',{}).items():
        def loader(lei=lei):
            payload=request('https://filings.xbrl.org/api/entities/'+lei+'/filings',{'sort':'-period_end','page[size]':5})
            filings=[]
            for row in payload.get('data',[]):
                a=row['attributes']
                if a.get('period_end','9999')>datetime.fromtimestamp(now,timezone.utc).date().isoformat():
                    continue
                filings.append(dict(form='ESEF / UKSEF',date=a.get('date_added','')[:10],end=a['period_end'],
                                    url=xbrl_url(a['viewer_url']),json_url=xbrl_url(a['json_url']),lei=lei))
            if not filings:
                raise DataError('No filing available for verified LEI')
            return filings
        filings=settings['_load']('XBRL:filings:'+symbol+':'+lei,86400,loader) or []
        if filings:
            latest=filings[0]
            facts=settings['_load']('XBRL:facts:'+symbol+':'+lei+':'+latest['json_url'],604800,
                lambda:xbrl_facts(request(latest['json_url']),latest['url'],latest['date'],expected_lei=lei)) or []
            results[symbol]=dict(filings=filings,financials=facts)
    return results


def collect_funds(settings, now):
    headers={'User-Agent':credential('SEC_USER_AGENT')}
    load=settings['_load']
    payload=load('SEC:fund-map',86400,lambda:request('https://www.sec.gov/files/company_tickers_mf.json',headers=headers)) or {}
    mapping={}
    for values in payload.get('data',[]):
        row=dict(zip(payload.get('fields',[]),values))
        symbol=row.get('symbol') or row.get('ticker')
        if symbol:
            mapping[symbol]=row
    results={}
    for symbol in settings.get('funds',[]):
        identity=mapping.get(symbol)
        if not identity:
            def unavailable():
                raise DataError('No SEC series mapping; fund may not report N-PORT')
            load('SEC:holdings:'+symbol+':unmapped',86400,unavailable)
            continue
        def loader(identity=identity):
            cik=int(identity['cik']); series=identity['seriesId']
            recent=request(f'https://data.sec.gov/submissions/CIK{cik:010d}.json',headers=headers).get('filings',{}).get('recent',{})
            inspected=0
            for i,form in enumerate(recent.get('form',[])):
                if form not in ('NPORT-P','NPORT-P/A'):
                    continue
                inspected+=1
                if inspected>12:
                    break
                accession=recent['accessionNumber'][i].replace('-','')
                document=recent['primaryDocument'][i]
                if not re.fullmatch(r'\d{18}',accession) or not re.fullmatch(r'[\w.-]+\.xml',document):
                    continue
                url=f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}'
                try:
                    parsed=nport_holdings(read_document(url,headers),series)
                except DataError as exc:
                    if 'series' in str(exc):
                        continue
                    raise
                if parsed['as_of']>datetime.fromtimestamp(now,timezone.utc).date().isoformat():
                    raise DataError('N-PORT report date is in the future')
                return dict(parsed,url=url)
            raise DataError('Matching N-PORT series not found in bounded recent filings')
        result=load('SEC:holdings:'+symbol+':'+str(identity.get('cik'))+':'+str(identity.get('seriesId')),86400,loader)
        if result:
            results[symbol]=result
    return results


def collect(settings, now):
    budget=settings.get('_budget')
    if budget is None:
        budget=dict(remaining=settings['max_requests'],deadline=time.monotonic()+settings['max_seconds'])
    token=_budget.set(budget)
    try:
        return _collect(settings,now)
    finally:
        _budget.reset(token)


def _collect(settings, now):
    """Bounded loader supplied by research refresh owns caching and diagnostics."""
    output=dict(connections=[],quotes=[],crypto=[],economy=[],europe={},funds={})
    def enabled(name, keys, purpose, url):
        missing=[key for key in keys if not credential(key)]
        output['connections'].append(dict(id=name,purpose=purpose,missing=missing,url=url,
            status='configuration_required' if missing else 'not_verified'))
        return not missing
    load=settings['_load']
    enabled('Kraken',[],'BTC/USD and ETH/USD research quotes','https://docs.kraken.com/api-reference/market-data/get-ticker-information')
    output['quotes']+=load('Kraken:quotes',60,lambda:kraken_rows(request('https://api.kraken.com/0/public/Ticker',{'pair':'XBTUSD,ETHUSD'}))) or []
    if enabled('Alpaca',['APCA_API_KEY_ID','APCA_API_SECRET_KEY'],'IEX stock quote observations','https://alpaca.markets/data'):
        symbols=','.join(settings.get('stocks',[])[:200])
        if symbols:
            headers={'APCA-API-KEY-ID':credential('APCA_API_KEY_ID'),'APCA-API-SECRET-KEY':credential('APCA_API_SECRET_KEY')}
            def quotes():
                rows=alpaca_quotes(request('https://data.alpaca.markets/v2/stocks/quotes/latest',{'symbols':symbols,'feed':'iex'},headers),time.time())
                if not rows: raise DataError('No valid IEX quotes')
                return rows
            output['quotes']+=load('Alpaca:quotes',60,quotes) or []
    if enabled('CoinGecko',['COINGECKO_DEMO_API_KEY'],'Crypto market cap, volume and daily change','https://www.coingecko.com/en/api/pricing'):
        def crypto():
            rows=coingecko_rows(request('https://api.coingecko.com/api/v3/coins/markets',
                {'vs_currency':'usd','order':'market_cap_desc','per_page':30,'page':1,'sparkline':'false'},
                {'x-cg-demo-api-key':credential('COINGECKO_DEMO_API_KEY')}),time.time())
            if not rows: raise DataError('No dated CoinGecko market rows')
            return rows
        output['crypto']=load('CoinGecko:markets',900,crypto) or []
    enabled('BLS',[],'Direct unemployment observations; optional BLS_API_KEY','https://www.bls.gov/developers/')
    def bls():
        key=credential('BLS_API_KEY')
        url='https://api.bls.gov/publicAPI/'+('v2' if key else 'v1')+'/timeseries/data/LNS14000000'
        rows=bls_series(request(url,{'registrationkey':key} if key else None),'LNS14000000')
        if not rows: raise DataError('No BLS monthly observations')
        return rows
    history=load('BLS:unemployment',86400,bls) or []
    output['economy'].append(series_record('BLS:LNS14000000','Unemployment / BLS direct','%',history,'BLS','https://www.bls.gov/charts/employment-situation/civilian-unemployment-rate.htm',now))
    if enabled('EIA',['EIA_API_KEY'],'Daily WTI and Brent spot prices; not live futures','https://www.eia.gov/opendata/register.php'):
        for series,name in [('RWTC','WTI spot / EIA'),('RBRTE','Brent spot / EIA')]:
            def energy(series=series):
                rows=eia_series(request('https://api.eia.gov/v2/petroleum/pri/spt/data/',{
                    'api_key':credential('EIA_API_KEY'),'frequency':'daily','data[0]':'value','facets[series][]':series,
                    'sort[0][column]':'period','sort[0][direction]':'desc','length':1000}),series)
                if not rows: raise DataError('No EIA spot observations')
                return rows
            history=load('EIA:'+series,86400,energy) or []
            output['economy'].append(series_record('EIA:'+series,name,'USD per barrel',history,'EIA','https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm',now))
    enabled('XBRL',[],'European financials for explicitly mapped LEIs','https://filings.xbrl.org/')
    output['europe']=collect_xbrl(settings,now)
    if enabled('SEC',['SEC_USER_AGENT'],'Company filings and series-matched N-PORT fund holdings','https://www.sec.gov/about/developer-resources'):
        output['funds']=collect_funds(settings,now)
    enabled('FRED',[],'Macro series; optional FRED_API_KEY with public CSV fallback','https://fred.stlouisfed.org/docs/api/api_key.html')
    enabled('RSS',[],'Publisher headlines and official announcements','https://www.federalreserve.gov/feeds/feeds.htm')
    enabled('Yahoo',[],'Delayed personal research history; unofficial access','https://github.com/ranaroussi/yfinance')
    enabled('Nasdaq',[],'Best-effort IPO calendar; not a licensed real-time feed','https://www.nasdaq.com/market-activity/ipos')
    enabled('Marketaux',['MARKETAUX_API_TOKEN'],'Optional existing technical-news integration','https://www.marketaux.com/')
    output['connections'].append(dict(id='TradingView',purpose='Display widgets only; isolated iframe compatibility fix still required',
                                     missing=[],status='display_only',url='https://www.tradingview.com/widget-docs/'))
    return output


def series_record(ident,name,unit,history,source,url,now):
    today=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
    history=[row for row in history if row['date']<=today]
    valid=[row for row in history if row['value'] is not None]
    return dict(id=ident,name=name,unit=unit,transform='level',history=history,
                value=valid[-1]['value'] if valid else None,previous=valid[-2]['value'] if len(valid)>1 else None,
                date=valid[-1]['date'] if valid else None,source=source,url=url)


def merge(snapshot, supplemental):
    snapshot['api_data']=supplemental
    economy={row['id']:row for row in snapshot.get('economy',[])}
    economy.update({row['id']:row for row in supplemental['economy']})
    snapshot['economy']=list(economy.values())
    for row in snapshot.get('instruments',[]):
        extra=supplemental['europe'].get(row['symbol'])
        if extra:
            row['financials']=[r for r in row.get('financials',[]) if r.get('source')!='European XBRL']+extra['financials']
            row['filings']=[r for r in row.get('filings',[]) if r.get('form')!='ESEF / UKSEF']+extra['filings']
        fund=supplemental['funds'].get(row['symbol'])
        if fund:
            row.update(holdings=fund['holdings'],holdings_as_of=fund['as_of'],holdings_source='SEC N-PORT',holdings_url=fund['url'])
    return snapshot


def connection_status(snapshot, now=None):
    """Describe verified resource coverage, not merely configured credentials."""
    if now is None:
        now=max(finite(snapshot.get(key)) or 0 for key in ('generated_at','api_refreshed_at'))
    def resource_status(resource):
        status=resource.get('status','unavailable')
        fetched=finite(resource.get('fetched_at')) or 0
        ttl=finite(resource.get('max_age_seconds'))
        if status=='ok':
            if fetched<=0 or fetched>now or ttl is None or ttl<=0:
                return 'unverified'
            if resource.get('error') or now-fetched>=ttl:
                return 'stale'
        return status
    for connection in snapshot.get('api_data',{}).get('connections',[]):
        if connection['status'] in ('configuration_required','display_only'):
            continue
        prefix='Feed' if connection['id']=='RSS' else connection['id']
        resources=[r for r in snapshot.get('resources',[]) if r['id'].startswith(prefix+':')]
        statuses=[resource_status(r) for r in resources]
        connection.update(resources_total=len(resources),resources_ok=statuses.count('ok'),
            resources_stale=statuses.count('stale'),
            resources_unverified=statuses.count('unverified'),
            resources_unavailable=sum(status not in ('ok','stale','unverified') for status in statuses),
            last_success_at=max((r.get('fetched_at') for r in resources
                if 0<(finite(r.get('fetched_at')) or 0)<=now),default=None),
            last_attempt_at=max((r.get('attempted_at') for r in resources
                if 0<(finite(r.get('attempted_at')) or 0)<=now),default=None))
        connection['status']='not_verified'
        if resources:
            connection['status']='available' if set(statuses)=={'ok'} else 'partial' if 'ok' in statuses else 'stale' if 'stale' in statuses else 'not_verified' if 'unverified' in statuses else 'unavailable'


def refresh_sources(store,settings,now):
    """Refresh optional APIs without relabelling or replacing older research history."""
    snapshot=copy.deepcopy(store.get('research-snapshot') or empty_snapshot('live',now))
    budget=dict(remaining=settings['max_requests'],deadline=time.monotonic()+settings['max_seconds'])
    resources={r['id']:r for r in snapshot.get('resources',[])}
    attempted=set()
    def load(key,ttl,loader):
        saved=store.get('research-cache:'+key,{})
        retry=settings.get('_force',False) and bool(saved.get('error')) and key not in attempted
        resource=cached_resource(store,key,ttl,now,loader,force=retry)
        attempted.add(key)
        resources[key]={k:v for k,v in resource.items() if k!='data'}
        return resource['data']
    supplemental=collect(dict(settings,_load=load,_budget=budget),now)
    merge(snapshot,supplemental)
    snapshot['resources']=list(resources.values())
    snapshot['api_refreshed_at']=now
    snapshot['api_request_count']=settings['max_requests']-budget['remaining']
    connection_status(snapshot)
    store.put('research-snapshot',snapshot)
    return snapshot
