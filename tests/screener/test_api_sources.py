"""Provider contracts: identity, time, units, missing keys and public output."""
import importlib
import json
from unittest.mock import patch

import pytest


def api():
    assert importlib.util.find_spec('screener.api_sources'), 'Public API integrations are missing'
    return importlib.import_module('screener.api_sources')


def test_kraken_retrieval_time_is_not_quote_time_and_spread_is_validated():
    payload = {'error': [], 'result': {'XXBTZUSD': {'a':['101','1','1'], 'b':['100','1','1'],
               'c':['100.5','1'], 'v':['1','20'], 'p':['100','99'], 't':[1,2], 'l':['98','97'], 'h':['102','103'], 'o':'99'}}}
    row = api().kraken_rows(payload)[0]
    assert (row['symbol'], row['bid'], row['ask'], row['price'], row['observed_at']) == ('BTC/USD',100,101,100.5,None)
    assert row['execution_eligible'] is False
    payload['result']['XXBTZUSD']['b'] = ['102']
    with pytest.raises(ValueError):
        api().kraken_rows(payload)


def test_xbrl_excludes_segments_preserves_period_unit_and_deduplicates():
    dims = dict(concept='ifrs-full:Revenue', entity='scheme:LEI', period='2024-01-01T00:00:00/2025-01-01T00:00:00',unit='iso4217:EUR')
    payload = {'documentInfo':{},'facts': {'a':{'value':'100','dimensions':dims},
        'b':{'value':'100','dimensions':dims},'segment':{'value':'25','dimensions':dict(dims,region='Europe')},
        'nan':{'value':'NaN','dimensions':dict(dims,concept='ifrs-full:Assets')},
        'bad_period':{'value':'2','dimensions':dict(dims,period='forever')}}}
    rows = api().xbrl_facts(payload, 'https://filings.xbrl.org/report', '2025-03-01')
    assert len(rows) == 1
    assert (rows[0]['value'],rows[0]['start'],rows[0]['end'],rows[0]['unit']) == (100,'2024-01-01','2024-12-31','EUR')
    assert rows[0]['concept'] == 'ifrs-full:Revenue'


NPORT = '''<edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData>
<genInfo><seriesId>S000001</seriesId><repPdDate>2025-12-31</repPdDate></genInfo><invstOrSecs>
<invstOrSec><name>Apple</name><cusip>037833100</cusip><identifiers><ticker value="AAPL"/></identifiers><pctVal>8.5</pctVal><assetCat>EC</assetCat></invstOrSec>
<invstOrSec><name>Bond without ticker</name><cusip>123456789</cusip><pctVal>2</pctVal><assetCat>DB</assetCat></invstOrSec>
</invstOrSecs></formData></edgarSubmission>'''


def test_nport_cannot_use_another_fund_series_or_renormalize_weights():
    result = api().nport_holdings(NPORT, 'S000001')
    assert result['as_of'] == '2025-12-31'
    assert result['holdings'][0]['weight'] == .085
    assert result['holdings'][1]['symbol'] == 'CUSIP:123456789'
    with pytest.raises(ValueError, match='series'):
        api().nport_holdings(NPORT, 'S000999')


def test_bls_skips_annual_averages_and_sorts_months():
    payload = {'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'LNS14000000','data':[
        {'year':'2025','period':'M13','value':'99'}, {'year':'2025','period':'M02','value':'4.1'},
        {'year':'2025','period':'M01','value':'4.0'}]}]}}
    rows = api().bls_series(payload,'LNS14000000')
    assert rows == [{'date':'2025-01-01','value':4.0},{'date':'2025-02-01','value':4.1}]


def test_eia_preserves_missing_values_and_selects_requested_series():
    rows = api().eia_series({'response':{'data':[
        {'period':'2025-01-02','series':'RWTC','value':'NA','units':'$/BBL'},
        {'period':'2025-01-01','series':'RWTC','value':'75','units':'$/BBL'},
        {'period':'2025-01-01','series':'RBRTE','value':'79','units':'$/BBL'}]}},'RWTC')
    assert rows == [{'date':'2025-01-01','value':75.0},{'date':'2025-01-02','value':None}]


def test_alpaca_keeps_provider_time_and_rejects_future_or_crossed_quote():
    payload = {'quotes':{'SPY':{'bp':100,'ap':101,'t':'2025-01-01T00:00:00Z'}}}
    assert api().alpaca_quotes(payload,1735689601)[0]['observed_at'] == '2025-01-01T00:00:00Z'
    assert api().alpaca_quotes(payload,1735689500) == []
    payload['quotes']['SPY']['bp'] = 102
    assert api().alpaca_quotes(payload,1735689601) == []


def test_coingecko_keeps_identity_and_does_not_turn_missing_price_into_zero():
    rows = api().coingecko_rows([{'id':'bitcoin','symbol':'btc','name':'Bitcoin','current_price':100,
        'market_cap':200,'total_volume':20,'price_change_percentage_24h':2,'last_updated':'2025-01-01T00:00:00Z'},
        {'id':'unknown','symbol':'btc','current_price':None}],1735689601)
    assert len(rows) == 1
    assert rows[0]['id'] == 'bitcoin' and rows[0]['change'] == .02


def test_missing_credentials_are_explicit_and_never_called():
    module = api()
    from screener.research import load_settings
    settings=load_settings(None,['SPY'])
    calls=[]
    settings['_load']=lambda key,ttl,loader: calls.append(key) or None
    with patch.dict('os.environ',{},clear=True):
        result=module.collect(settings,1735689601)
    statuses={r['id']:r for r in result['connections']}
    assert statuses['Alpaca']['missing'] == ['APCA_API_KEY_ID','APCA_API_SECRET_KEY']
    assert statuses['SEC']['missing'] == ['SEC_USER_AGENT']
    assert statuses['EIA']['status'] == 'configuration_required'
    assert 'Kraken:quotes' in calls
    assert not any(k.startswith(('Alpaca:','EIA:','CoinGecko:','SEC:')) for k in calls)


def test_sources_refresh_preserves_existing_research_and_redacts_failures(tmp_path):
    from screener import research
    from screener.runtime import Store
    module=api()
    store=Store(tmp_path/'state.sqlite3')
    try:
        original={'version':1,'mode':'live','generated_at':10,'instruments':[{'symbol':'SPY','history':[{'date':'2025-01-01','close':100}]}],
                  'economy':[],'resources':[],'news':[{'title':'Saved headline'}]}
        store.put('research-snapshot',original)
        settings=research.load_settings(None,['SPY'])
        settings['xbrl_entities']={}
        with patch.dict('os.environ',{'EIA_API_KEY':'private-secret'},clear=True),patch.object(module,'read_text',side_effect=RuntimeError('private-secret')):
            result=module.refresh_sources(store,settings,1735689601)
        assert result['instruments'] == original['instruments']
        assert result['news'] == original['news']
        assert 'private-secret' not in json.dumps(result)
        assert any(r['status']=='unavailable' for r in result['resources'])
        assert result['generated_at']==10  # Supplementary refresh cannot relabel old research as fresh.
    finally:
        store.close()


def test_network_budget_counts_nested_requests_and_stops_before_transport():
    module=api()
    from screener.research import load_settings
    settings=load_settings(None,[])
    settings['max_requests']=1
    settings['_load']=lambda key,ttl,loader: loader()
    response=json.dumps({'error':[],'result':{'XXBTZUSD':{'a':['101'],'b':['100'],'c':['100.5']}}})
    with patch.dict('os.environ',{},clear=True),patch.object(module,'read_text',return_value=response) as transport:
        with pytest.raises(ValueError,match='budget'):
            module.collect(settings,1735689601)
        assert transport.call_count==1


def test_fred_api_failure_falls_back_to_public_csv_without_leaking_key():
    from screener import research_sources as sources
    from screener.research import load_settings
    settings=load_settings(None,[])
    settings['_load']=lambda key,ttl,loader: loader()
    calls=[]
    def read(url,headers=None):
        calls.append(url)
        if 'api.stlouisfed.org' in url:
            raise ValueError('secret-key')
        return 'observation_date,DFF\n2025-01-01,4.5\n2025-01-02,4.25'
    with patch.dict('os.environ',{'FRED_API_KEY':'secret-key'},clear=True),patch.object(sources,'read_text',side_effect=read),patch.object(sources,'MACRO',[('DFF','Fed funds','%','level')]):
        rows=sources.collect_economy(settings,1735862400)
    assert len(calls)==2
    assert rows[0]['value']==4.25
    assert 'secret-key' not in json.dumps(rows)


def test_quote_created_during_refresh_uses_response_receipt_time():
    from screener.research import load_settings
    module=api(); settings=load_settings(None,['SPY'])
    settings['_load']=lambda key,ttl,loader: loader() if key.startswith(('Alpaca:','CoinGecko:')) else None
    quote_time='2025-01-01T00:00:01Z'
    def request(url,*args):
        if 'alpaca' in url:
            return {'quotes':{'SPY':{'bp':100,'ap':101,'t':quote_time}}}
        return [{'id':'bitcoin','symbol':'btc','current_price':100,'last_updated':quote_time}]
    with patch.dict('os.environ',{'APCA_API_KEY_ID':'fixture','APCA_API_SECRET_KEY':'fixture','COINGECKO_DEMO_API_KEY':'fixture'},clear=True),patch.object(module,'request',side_effect=request),patch.object(module.time,'time',return_value=1735689602):
        result=module.collect(settings,1735689600)
    assert result['quotes'][0]['observed_at']==quote_time
    assert result['crypto'][0]['observed_at']==quote_time


def test_custom_europe_universe_does_not_inherit_inapplicable_lei(tmp_path):
    from screener.research import load_settings
    path=tmp_path/'research.json'; path.write_text('{"europe":[]}')
    assert load_settings(path,[])['xbrl_entities']=={}
    path.write_text('{"europe":[],"xbrl_entities":{"ASML.AS":"724500Y6DUVHQD6OXN27"}}')
    with pytest.raises(ValueError):
        load_settings(path,[])


def test_xbrl_cache_changes_with_entity_and_filing():
    module=api(); cached={}; calls=[]; report=['first']
    def load(key,ttl,loader):
        if key not in cached: cached[key]=loader()
        return cached[key]
    def request(url,*args):
        calls.append(url)
        if '/api/entities/' in url:
            return {'data':[{'attributes':{'period_end':'2024-12-31','date_added':'2025-02-01','viewer_url':'/'+report[0], 'json_url':'/'+report[0]+'.json'}}]}
        return {'facts':{}}
    with patch.object(module,'request',side_effect=request):
        for lei in ['A'*20,'B'*20]:
            module.collect_xbrl({'xbrl_entities':{'ABC':lei},'_load':load},1738454400)
        assert len([url for url in calls if '/api/entities/' in url])==2
        cached={k:v for k,v in cached.items() if ':filings:' not in k}
        report[0]='amended'
        module.collect_xbrl({'xbrl_entities':{'ABC':'B'*20},'_load':load},1738454400)
    assert any(url.endswith('/amended.json') for url in calls)


def test_full_refresh_shares_remaining_budget_with_nested_api_requests(tmp_path):
    from screener import research, research_sources
    from screener.runtime import Store
    module=api(); settings=research.load_settings(None,[])
    settings.update(api_sources=True,funds=[],europe=[],proxies=[],xbrl_entities={},max_requests=3)
    def economy(settings,now):
        settings['_load']('FRED:fixture',60,lambda:[])
        return []
    def supplemental(settings,now):
        def nested():
            for i in range(4): module.read_document('https://fixture.test/'+str(i))
        settings['_load']('SEC:holdings:fixture',60,nested)
        return dict(connections=[],quotes=[],crypto=[],economy=[],europe={},funds={})
    store=Store(tmp_path/'state.sqlite3')
    try:
        with patch.object(research_sources,'collect_economy',side_effect=economy),patch.object(research_sources,'collect_releases',return_value=[]),patch.object(research_sources,'collect_ipos',return_value=[]),patch.object(research_sources,'collect_news',return_value=[]),patch.object(module,'_collect',side_effect=supplemental),patch.object(module,'read_text',return_value='{}') as transport:
            result=research.refresh(store,settings,1735689600)
        assert transport.call_count==2
        assert result['request_count']==3
    finally: store.close()


def test_sec_symbol_map_loads_matching_series_and_reports_unmapped_fund(tmp_path):
    from screener import research
    from screener.runtime import Store
    module=api(); settings=research.load_settings(None,[])
    settings.update(funds=['VTI','UNKNOWN'],xbrl_entities={})
    def response(url,headers=None):
        if 'company_tickers_mf' in url:
            return json.dumps({'fields':['cik','seriesId','classId','symbol'],'data':[[123,'S000001','C000001','VTI']]})
        if '/submissions/' in url:
            return json.dumps({'filings':{'recent':{'form':['NPORT-P'],'accessionNumber':['0000000123-26-000001'],'primaryDocument':['primary_doc.xml']}}})
        if '/Archives/' in url: return NPORT
        raise RuntimeError('Unrelated provider unavailable')
    store=Store(tmp_path/'state.sqlite3')
    try:
        with patch.dict('os.environ',{'SEC_USER_AGENT':'Fixture contact@example.invalid'},clear=True),patch.object(module,'read_text',side_effect=response),patch.object(module.time,'sleep'):
            result=module.refresh_sources(store,settings,1768000000)
        assert result['api_data']['funds']['VTI']['holdings'][0]['symbol']=='AAPL'
        missing=[r for r in result['resources'] if r['id'].startswith('SEC:holdings:UNKNOWN')]
        assert missing and missing[0]['status']=='unavailable'
    finally: store.close()


def test_xbrl_facts_reject_another_entity():
    fact={'value':'100','dimensions':{'concept':'ifrs-full:Assets','unit':'iso4217:EUR','period':'2025-01-01T00:00:00','entity':'lei:'+'B'*20}}
    with pytest.raises(ValueError,match='entity'):
        api().xbrl_facts({'facts':{'a':fact}},'https://filings.xbrl.org/report','2025-02-01',expected_lei='A'*20)
