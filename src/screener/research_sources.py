"""Free-source adapters. No research records enter the strategy engine."""
import csv
import io
import json
import hashlib
import os
import re
import ssl
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, build_opener

from .research import finite, safe_url, returns, ratio
from .shared import DataError, get_json, NoRedirect


def read_text(url, headers=None):
    request=Request(url,headers={'User-Agent':'MarketWatch/1.0 public research','Accept':'*/*',**(headers or {})})
    try:
        with build_opener(NoRedirect()).open(request,timeout=15) as response:
            data=response.read(10*1024*1024+1)
            if len(data)>10*1024*1024:
                raise DataError('Source exceeds 10 MiB response limit')
            return data.decode('utf-8-sig','replace')
    except Exception as exc:
        if sys.platform=='darwin' and isinstance(getattr(exc,'reason',None),ssl.SSLCertVerificationError):
            # Native macOS curl uses the system trust store; certificate verification stays enabled.
            args=['/usr/bin/curl','--silent','--show-error','--fail','--max-time','15','--max-filesize','10485760',
                  '--proto','=http,https']
            for key,value in (headers or {}).items():
                args+=['--header',key+': '+value]
            result=subprocess.run(args+[url],capture_output=True,timeout=18)
            if result.returncode==0:
                return result.stdout.decode('utf-8-sig','replace')
        raise DataError(f'Public source HTTP {exc.code}' if hasattr(exc,'code') else 'Public source unavailable') from None


MACRO=[('CPIAUCSL','Consumer prices (CPI)','% year over year','yoy'),
       ('CPILFESL','Core CPI','% year over year','yoy'),('PCEPILFE','Core PCE','% year over year','yoy'),
       ('UNRATE','Unemployment','%','level'),('PAYEMS','Jobs added','thousands, monthly change','difference'),
       ('ICSA','Initial jobless claims','people','level'),('A191RL1Q225SBEA','GDP growth','% annualized quarterly','level'),
       ('RSAFS','Retail sales','% month over month','mom'),('INDPRO','Industrial production','% year over year','yoy'),
       ('UMCSENT','Consumer sentiment','index','level'),('DFF','Fed funds rate','%','level'),
       ('DGS2','2-year Treasury','%','level'),('DGS10','10-year Treasury','%','level'),
       ('T10Y2Y','10-year minus 2-year','percentage points','level'),('MORTGAGE30US','30-year mortgage','%','level'),
       ('BAMLH0A0HYM2','High-yield credit spread','percentage points','level'),
       ('DCOILWTICO','WTI oil','$ per barrel','level'),('DTWEXBGS','Broad dollar index','index','level')]


def parse_macro(text, transform):
    rows=[]
    for raw in csv.reader(io.StringIO(text)):
        if len(raw)>=2 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw[0]):
            rows.append(dict(date=raw[0],value=finite(raw[1])))
    originals={r['date'][:7]:r['value'] for r in rows}
    previous=None
    for row in rows:
        value=row['value']
        if transform=='yoy':
            key=f'{int(row["date"][:4])-1:04d}'+row['date'][4:7]
            base=originals.get(key)
            row['value']=(value/base-1)*100 if value is not None and base is not None and base>0 else None
        elif transform in ('mom','difference'):
            row['value']=((value/previous-1)*100 if transform=='mom' and previous>0 else value-previous) if value is not None and previous is not None else None
        previous=value
    return rows[-2600:]


def collect_economy(settings,now):
    records=[]
    for symbol,name,unit,transform in MACRO:
        def loader(symbol=symbol,transform=transform):
            start=datetime.fromtimestamp(now,timezone.utc).date()-timedelta(days=12*366)
            text=read_text('https://fred.stlouisfed.org/graph/fredgraph.csv?id='+symbol+'&cosd='+start.isoformat())
            values=parse_macro(text,transform)
            if not values:
                raise DataError('FRED returned no observations')
            return values
        history=settings['_load']('FRED:'+symbol,86400,loader) or []
        valid=[r for r in history if r['value'] is not None]
        records.append(dict(id=symbol,name=name,unit=unit,transform=transform,history=history,
                            value=valid[-1]['value'] if valid else None,previous=valid[-2]['value'] if len(valid)>1 else None,
                            date=valid[-1]['date'] if valid else None,source='FRED / Federal Reserve Bank of St. Louis',
                            url='https://fred.stlouisfed.org/series/'+symbol))
    return records


def parse_ics(text,source,url):
    records=[]
    text=re.sub(r'\r?\n[ \t]','',text)
    for event in text.split('BEGIN:VEVENT')[1:]:
        fields={}
        zone='UTC'
        for line in event.splitlines():
            if ':' not in line:
                continue
            key,value=line.split(':',1)
            if key.startswith('DTSTART'):
                zone=key.split('TZID=',1)[-1].split(';')[0] if 'TZID=' in key else 'UTC' if value.endswith('Z') else 'America/New_York'
            fields[key.split(';')[0]]=value
        start=fields.get('DTSTART','')
        if not re.fullmatch(r'\d{8}(T\d{6}Z?)?',start):
            continue
        when=datetime.strptime(start[:8],'%Y%m%d')
        records.append(dict(date=when.date().isoformat(),time=start[9:11]+':'+start[11:13] if 'T' in start else '',
                            timezone=zone,name=fields.get('SUMMARY','Release').replace('\\,',','),source=source,url=safe_url(fields.get('URL')) or url))
    return records


def collect_releases(settings,now):
    sources=[('BLS','https://www.bls.gov/schedule/news_release/bls.ics'),
             ('BEA','https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics')]
    records=[]
    for name,url in sources:
        def loader(name=name,url=url):
            rows=parse_ics(read_text(url),name,url)
            if not rows:
                raise DataError('Release calendar has no usable events')
            return rows
        records+=settings['_load']('Calendar:'+name,86400,loader) or []
    return sorted(records,key=lambda r:(r['date'],r['time']))


def date_string(value):
    text=str(value or '')
    if re.match(r'^\d{4}-\d{2}-\d{2}',text):
        return text[:10]
    for fmt in ('%m/%d/%Y','%b %d, %Y','%B %d, %Y'):
        try:
            return datetime.strptime(text,fmt).date().isoformat()
        except ValueError:
            pass
    return None


def normalize_ipos(payload):
    data=payload.get('data') or {}
    output=[]
    for key,status in [('upcoming','expected'),('priced','priced'),('filed','filed'),('withdrawn','withdrawn')]:
        section=data.get(key) or {}
        for row in section.get('rows') or []:
            output.append(dict(name=str(row.get('companyName') or row.get('company') or ''),symbol=str(row.get('proposedTickerSymbol') or row.get('symbol') or ''),
                               status=status,date=date_string(row.get('expectedPriceDate') or row.get('pricedDate') or row.get('filedDate') or row.get('withdrawnDate')),
                               price=str(row.get('proposedSharePrice') or row.get('offerPrice') or '—'),exchange=str(row.get('exchange') or '—'),
                               shares=str(row.get('sharesOffered') or '—'),amount=str(row.get('dollarValueOfSharesOffered') or '—'),
                               source='Nasdaq / estimated dates',url='https://www.nasdaq.com/market-activity/ipos'))
    return output


def collect_ipos(settings,now):
    month=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m')
    def loader():
        raw=json.loads(read_text('https://api.nasdaq.com/api/ipo/calendar?date='+month,{'Accept':'application/json','Origin':'https://www.nasdaq.com'}))
        if not isinstance(raw.get('data'),dict):
            raise DataError('Nasdaq calendar unavailable')
        return normalize_ipos(raw)
    return settings['_load']('Nasdaq:ipos:'+month,86400,loader) or []


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.blocked=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):
            self.blocked+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.blocked=max(0,self.blocked-1)
    def handle_data(self,data):
        if not self.blocked:
            self.parts.append(data)


def plain(value):
    parser=PlainText()
    parser.feed(str(value or ''))
    return ' '.join(' '.join(parser.parts).split())


def canonical_url(value):
    value=safe_url(value)
    if not value:
        return ''
    parts=urlsplit(value)
    query=[(k,v) for k,v in parse_qsl(parts.query) if not k.startswith('utm_') and k not in ('fbclid','gclid')]
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),''))


def parse_feed(text,source):
    root=ET.fromstring(text)
    rows=[]
    seen=set()
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item','entry'):
            continue
        fields={child.tag.split('}')[-1]:child for child in node}
        def value(key):
            child=fields.get(key)
            return ''.join(child.itertext()) if child is not None else ''
        link=fields.get('link')
        url=canonical_url(link.get('href') or value('link')) if link is not None else ''
        if not url or url in seen:
            continue
        seen.add(url)
        published=value('pubDate') or value('published') or value('updated')
        try:
            when=parsedate_to_datetime(published)
        except (ValueError,TypeError):
            try:
                when=datetime.fromisoformat(published.replace('Z','+00:00'))
            except ValueError:
                when=None
        title=plain(value('title'))
        excerpt=plain(value('description') or value('summary') or value('encoded'))[:900]
        rows.append(dict(id=hashlib.sha256(url.encode()).hexdigest()[:20],title=title,excerpt=excerpt,url=url,publisher=source['name'],
                         category=source.get('category','Markets'),published=when.isoformat() if when else None,
                         tickers=re.findall(r'\$([A-Z]{1,6})\b',title+' '+excerpt),longform=bool(source.get('longform'))))
    return rows[:100]


def collect_news(settings,now):
    records=[]
    for source in settings['feeds']:
        def loader(source=source):
            rows=parse_feed(read_text(source['url']),source)
            if not rows:
                raise DataError('News feed contains no usable articles')
            return rows
        records+=settings['_load']('Feed:'+source['name'],14400,loader) or []
    unique={r['url']:r for r in records}
    output=sorted(unique.values(),key=lambda r:r.get('published') or '',reverse=True)[:300]
    for row in output:
        row['id']=hashlib.sha256(row['url'].encode()).hexdigest()[:20]
    return output


def normalize_holdings(rows):
    output=[]
    for row in rows:
        weight=finite(row.get('weight'))
        if isinstance(row.get('symbol'),str) and weight is not None and 0<weight<=1:
            output.append(dict(symbol=row['symbol'],weight=weight,name=str(row.get('name') or row['symbol'])))
    if sum(r['weight'] for r in output)>1.001:
        raise DataError('Holdings exceed 100%; cannot verify fund exposure')
    return output


def sec_facts(payload):
    output=[]
    concepts=('Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','NetIncomeLoss','Assets',
              'StockholdersEquity','LongTermDebt','CashAndCashEquivalentsAtCarryingValue',
              'NetCashProvidedByUsedInOperatingActivities','PaymentsToAcquirePropertyPlantAndEquipment',
              'EarningsPerShareDiluted','CommonStockDividendsPerShareCashPaid','ResearchAndDevelopmentExpense')
    for concept, data in payload.get('facts',{}).get('us-gaap',{}).items():
        if concept not in concepts:
            continue
        for unit, rows in data.get('units',{}).items():
            annual={}
            for row in rows:
                if row.get('form') not in ('10-K','10-K/A') or finite(row.get('val')) is None or not row.get('end'):
                    continue
                if row.get('start'):
                    duration=(datetime.fromisoformat(row['end'])-datetime.fromisoformat(row['start'])).days
                    if not 330<=duration<=400:
                        continue
                key=(row.get('start'),row['end'])
                if key not in annual or row.get('filed','')>annual[key].get('filed',''):
                    annual[key]=row
            for row in sorted(annual.values(),key=lambda r:r['end'],reverse=True)[:10]:
                output.append(dict(metric=concept,value=finite(row['val']),unit=unit,start=row.get('start'),
                                   end=row['end'],filed=row.get('filed'),accession=row.get('accn'),source='SEC EDGAR'))
    return output


def collect_sec(symbol, settings, now):
    agent=os.environ.get('SEC_USER_AGENT','').strip()
    if not agent:
        raise DataError('SEC_USER_AGENT is not configured; Yahoo financials remain available')
    load=settings['_load']
    headers={'User-Agent':agent}
    mapping=load('SEC:ticker-map',86400,lambda:json.loads(read_text('https://www.sec.gov/files/company_tickers.json',headers))) or {}
    item=next((r for r in mapping.values() if r.get('ticker')==symbol),None)
    if not item:
        return dict(facts=[],filings=[])
    cik=int(item['cik_str'])
    def request(url):
        time.sleep(.2)
        return json.loads(read_text(url,headers))
    facts=load('SEC:facts:'+symbol,86400,lambda:sec_facts(request(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'))) or []
    def filings():
        recent=request(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').get('filings',{}).get('recent',{})
        records=[]
        for i,accession in enumerate(recent.get('accessionNumber',[])[:30]):
            document=recent.get('primaryDocument',[])[i]
            records.append(dict(form=recent['form'][i],date=recent['filingDate'][i],
                                url=f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-","")}/{quote(document)}'))
        return records
    return dict(facts=facts,filings=load('SEC:filings:'+symbol,86400,filings) or [])


def frame_records(frame):
    if frame is None or frame.empty:
        return []
    records=[]
    for period,column in frame.items():
        for metric,value in column.items():
            value=finite(value)
            if value is not None:
                records.append(dict(metric=str(metric),value=value,end=period.date().isoformat(),source='Yahoo Finance'))
    return records


def discover(yf):
    records=[]
    for query in ('most_actives','day_gainers','day_losers'):
        records.extend(r['symbol'] for r in yf.screen(query,count=25).get('quotes',[]) if r.get('symbol'))
    return list(dict.fromkeys(records))


def earnings_records(frame,now):
    rows=[]
    if frame is None:
        return rows
    for when,row in frame.iterrows():
        reported=finite(row.get('Reported EPS'))
        rows.append(dict(type='earnings',date=when.date().isoformat(),time=when.strftime('%H:%M'),
                         timezone=str(when.tzinfo or 'Unknown'),status='reported' if reported is not None and when.timestamp()<=now else 'provider estimate',
                         estimate=finite(row.get('EPS Estimate')),actual=reported))
    return rows


def collect_instrument(symbol,settings,now):
    import yfinance as yf
    ticker=yf.Ticker(symbol)
    load=settings['_load']
    info=load('Yahoo:info:'+symbol,86400,lambda:json.loads(json.dumps(ticker.info,default=str))) or {}
    def history():
        frame=ticker.history(period='5y',auto_adjust=False,actions=True,timeout=15)
        rows=[]
        for when,row in frame.iterrows():
            # Daily observations can be delayed/in-progress: retain date and mark research, not a fill.
            if when.timestamp()>now:
                continue
            value=finite(row.get('Adj Close',row.get('Close')))
            price=finite(row.get('Close'))
            if value and value>0 and price and price>0:
                rows.append(dict(date=when.date().isoformat(),close=value,price=price,volume=finite(row.get('Volume')),
                                 dividend=finite(row.get('Dividends')),split=finite(row.get('Stock Splits'))))
        if not rows:
            raise DataError('No usable Yahoo price history')
        return rows
    hist=load('Yahoo:history:'+symbol,14400,history) or []
    quote_currency=info.get('currency')
    # London quotes are pence while Yahoo market caps are pounds. Normalize once.
    if info.get('currency') in ('GBp','GBX'):
        info={**info,'currency':'GBP'}
        hist=[{**row,**{key:row[key]/100 for key in ('price','close','dividend') if finite(row.get(key)) is not None}} for row in hist]
        if finite(info.get('regularMarketPrice')) is not None:
            info['regularMarketPrice']/=100
    region='EU' if symbol in settings['europe'] or (symbol in settings['proxies'] and (symbol.startswith('^') and symbol not in ('^GSPC','^DJI','^IXIC') or '=X' in symbol)) else 'US'
    kind='fund' if symbol in settings['funds'] or info.get('quoteType') in ('ETF','MUTUALFUND','MONEYMARKET') else 'stock'
    if symbol in settings['proxies'] and symbol not in settings['funds']:
        kind='proxy'
    metrics={name:finite(info.get(field)) for name,field in dict(market_cap='marketCap',pe='trailingPE',pb='priceToBook',
             revenue_growth='revenueGrowth',earnings_growth='earningsGrowth',operating_margin='operatingMargins',net_margin='profitMargins',
             roe='returnOnEquity',debt_equity='debtToEquity',dividend_yield='dividendYield',assets='totalAssets',expense='annualReportExpenseRatio',
             cash='totalCash',debt='totalDebt',revenue='totalRevenue',free_cash_flow='freeCashflow',current_ratio='currentRatio').items()}
    # Yahoo debt/equity is expressed in percent. All ratio metrics use fractions internally.
    if metrics['debt_equity'] is not None:
        metrics['debt_equity']/=100
    if metrics['dividend_yield'] is not None:
        metrics['dividend_yield']/=100  # Yahoo info provides percentage points, e.g. 0.32 means 0.32%.
    if metrics['pe'] is not None and metrics['pe']<=0:
        metrics['pe']=None
    metrics['fcf_margin']=ratio(metrics['free_cash_flow'],metrics['revenue'])
    metrics.update(returns(hist,hist[-1]['date']) if hist else returns([],''))
    volumes=[r['volume'] for r in hist[-21:-1] if r['volume'] is not None]
    metrics['relative_volume']=ratio(hist[-1]['volume'],sum(volumes)/len(volumes)) if hist and volumes else None
    metrics['dollar_volume']=hist[-1]['price']*hist[-1]['volume'] if hist and hist[-1]['volume'] is not None else None
    metrics['above50']=hist[-1]['close']>sum(r['close'] for r in hist[-50:])/50 if len(hist)>=50 else None
    metrics['above200']=hist[-1]['close']>sum(r['close'] for r in hist[-200:])/200 if len(hist)>=200 else None
    metrics['new_high']=hist[-1]['close']>=max(r['close'] for r in hist[-252:]) if len(hist)>=252 else None
    metrics['new_low']=hist[-1]['close']<=min(r['close'] for r in hist[-252:]) if len(hist)>=252 else None
    record=dict(symbol=symbol,name=str(info.get('longName') or info.get('shortName') or symbol),region=region,kind=kind,
                sector=str(info.get('sector') or 'Unknown'),country=str(info.get('country') or 'Unknown'),
                currency=str(info.get('currency') or ('USD' if region=='US' else 'Unknown')),price=hist[-1]['price'] if hist else finite(info.get('regularMarketPrice')),
                as_of=hist[-1]['date'] if hist else None,metrics=metrics,history=hist,family=str(info.get('fundFamily') or 'Unknown'),
                financial_currency=str(info.get('financialCurrency') or info.get('currency') or 'Unknown'),quote_type=str(info.get('quoteType') or ''),
                original_quote_currency=quote_currency,
                category=str(info.get('category') or 'Unknown'),description=str(info.get('longBusinessSummary') or ''),
                holdings=[],financials=[],filings=[],calendar=[],distributions=[],source='Yahoo Finance / delayed research snapshot')
    if settings.get('_core_only'):
        return record
    if kind=='stock':
        def financials():
            return frame_records(ticker.income_stmt)+frame_records(ticker.balance_sheet)+frame_records(ticker.cashflow)
        record['financials']=load('Yahoo:financials:'+symbol,86400,financials) or []
        for row in record['financials']:
            row['unit']=str(info.get('financialCurrency') or record['currency'])
        if region=='US' and os.environ.get('SEC_USER_AGENT'):
            sec=collect_sec(symbol,settings,now)
            record['financials']+=sec['facts']
            record['filings']=sec['filings']
    if kind=='fund':
        def funds():
            data=ticker.funds_data
            if data is None:
                return {}
            holdings=[]
            frame=data.top_holdings
            if frame is not None:
                holdings=normalize_holdings([dict(symbol=str(s),name=r.get('Name',s),weight=r.get('Holding Percent')) for s,r in frame.iterrows()])
            operations=data.fund_operations
            expense=None
            if operations is not None and not operations.empty and 'Annual Report Expense Ratio' in operations.index:
                expense=finite(operations.loc['Annual Report Expense Ratio'].iloc[0])
            overview=data.fund_overview or {}
            return dict(holdings=holdings,sectors={str(k):finite(v) for k,v in (data.sector_weightings or {}).items()},
                        family=str(overview.get('family') or overview.get('fundFamily') or ''),expense=expense)
        fund=load('Yahoo:fund:'+symbol,86400,funds) or {}
        record['holdings']=fund.get('holdings',[])
        record['sector_weights']=fund.get('sectors',{})
        record['holdings_as_of']=None  # Yahoo does not reliably expose the holdings reporting date.
        if fund.get('family'):
            record['family']=fund['family']
        if fund.get('expense') is not None:
            record['metrics']['expense']=fund['expense']
    if kind in ('stock','fund'):
        def calendar():
            raw=ticker.calendar or {} if kind=='stock' else {}
            rows=[]
            for field,typ in [('Earnings Date','earnings'),('Ex-Dividend Date','dividends')]:
                values=raw.get(field,[])
                if not isinstance(values,list):
                    values=[values]
                for when in values:
                    if hasattr(when,'isoformat'):
                        rows.append(dict(type=typ,date=when.isoformat()[:10],symbol=symbol,sector=record['sector'],
                                         status='provider estimate' if typ=='earnings' else 'provider date',
                                         amount=None,
                                         payment_date=str(raw.get('Dividend Date') or '')[:10],currency=record['currency']))
            return rows
        record['calendar']=load('Yahoo:calendar:'+symbol,86400,calendar) or []
        if kind=='stock':
            dated=load('Yahoo:earnings:'+symbol,86400,lambda:earnings_records(ticker.get_earnings_dates(limit=12),now)) or []
            dates={r['date'] for r in dated}
            record['calendar']=[r for r in record['calendar'] if r['type']!='earnings' or r['date'] not in dates]+dated
    record['distributions']=[dict(date=r['date'],amount=r['dividend'],currency=record['currency']) for r in hist if r.get('dividend')]
    return record
