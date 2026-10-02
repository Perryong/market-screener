import copy
import math
import pytest
from entrydesk.data import validate_bars, normalize_history
from entrydesk.factors import build_factors, validate_quote
from entrydesk.astra.calculations import macd_series, compute_rsi_factors
from entrydesk.astra.scoring import score_composite_alpha


def bars(n=100, step=3600, constant=False):
    return [dict(start=i*step, end=(i+1)*step, open=100 if constant else 100+i,
                 high=101 if constant else 101+i, low=99 if constant else 99+i,
                 close=100 if constant else 100+i, volume=100) for i in range(n)]


def test_validation_rejects_bad_incomplete_duplicate_and_nonfinite():
    good=bars(3)
    validate_bars(good, 10800)
    for field, value in [('open', True), ('close', None), ('volume', -1), ('high', math.nan), ('low', 500), ('start', -1)]:
        bad=copy.deepcopy(good); bad[0][field]=value
        with pytest.raises(ValueError): validate_bars(bad,10800)
    with pytest.raises(ValueError): validate_bars(good,10799)
    with pytest.raises(ValueError): validate_bars([good[0],good[0]],10800)


def test_missing_real_15m_is_not_fabricated():
    f=build_factors(bars(), [])
    assert f['trend_momentum']['rsi_15m'] is None
    assert f['volume_profile']['vwap'] is None
    assert not f['smart_money_derivatives']['available']
    assert f['microstructure']['obi_pct'] is None
    assert 'derivatives' in f['coverage']['unavailable']


def test_macd_and_scoring_parity():
    b=bars(); f=build_factors(b,bars(step=900))
    dif,dea,hist=macd_series([x['close'] for x in b])
    assert f['trend_momentum']['macd_hist']==round(hist[-1],6)
    assert f['trend_momentum']['macd_dif']==round(dif[-1],6)
    dup=copy.deepcopy(f)
    assert score_composite_alpha(dup)==f['composite_alpha_score']


def test_rsi_constant_up_down_and_missing():
    assert compute_rsi_factors([10]*20,[], 'RANGE')['rsi_1h']==50
    assert compute_rsi_factors(list(range(1,21)),[], 'BULL')['rsi_1h']==100
    assert compute_rsi_factors(list(range(20,0,-1)),[], 'BEAR')['rsi_1h']==0
    assert compute_rsi_factors([1]*3,[], 'RANGE')['rsi_1h'] is None


def test_actual_window_and_causal_prefix():
    f=build_factors(bars(),bars(20,900))
    assert f['volume_profile']['interval_seconds']==900
    assert f['volume_profile']['window_bars']==20
    assert f['volume_profile']['window_elapsed_seconds']==18000
    assert f['volatility_channel']['atr_1h']>0
    assert build_factors(bars()[:60],[])==build_factors(bars(60),[])
    with pytest.raises(ValueError): build_factors(bars(step=86400),[])


def test_missing_crossed_or_malformed_depth_fails_closed():
    for micro in [None,{}, {'bids':[[99,5]],'asks':[[100,1]]}, {'bids':[[101,5]],'asks':[[100,1]]}, {'bids':[[99,True]],'asks':[[100,1]]}]:
        f=build_factors(bars(),[],micro)
        assert not f['microstructure']['depth_reliable']
        assert f['microstructure']['obi_pct'] is None
    f=build_factors(bars(),[],{'bids':[[99,5,0,3],[98,5,0,3],[97,5,0,3]],'asks':[[100,1,0,3],[101,1,0,3],[102,1,0,3]]})
    assert f['microstructure']['depth_reliable']
    assert f['microstructure']['obi_pct']>0


def test_strict_quote_geometry():
    assert validate_quote('BUY_LONG',100,120,90)[0]
    assert validate_quote('SELL_SHORT',100,80,110)[0]
    for a,e,t,s in [('BUY_LONG',True,3,.5),('BUY_LONG',100,119,90),('BUY_LONG',100,120,100),('SELL_SHORT',100,120,90),('BUY_LONG',100,math.inf,90),('WAIT',100,120,90)]:
        assert not validate_quote(a,e,t,s)[0]


def test_normalize_drops_only_unfinished_and_rejects_bad_rows():
    import pandas as pd
    idx=pd.to_datetime(['2026-10-02T14:30:00Z','2026-10-02T15:30:00Z'])
    frame=pd.DataFrame(dict(Open=[100,101],High=[102,103],Low=[99,100],Close=[101,102],Volume=[5,6]),index=idx)
    now=idx[1].timestamp()+100
    assert len(normalize_history(frame,3600,now,'crypto'))==1
    frame.loc[idx[0],'High']=math.nan
    with pytest.raises(ValueError): normalize_history(frame,3600,now,'crypto')


def test_equity_calendar_holiday_weekend_and_early_close():
    import pandas as pd
    from entrydesk.data import _calendar
    now=pd.Timestamp('2026-11-28T18:00:00Z').timestamp()
    cal=_calendar(now)
    assert not cal.is_open_on_minute(pd.Timestamp('2026-11-28T15:00:00Z'))
    assert not cal.is_open_on_minute(pd.Timestamp('2026-11-26T15:00:00Z'))
    idx=pd.to_datetime(['2026-11-27T17:30:00Z'])
    frame=pd.DataFrame(dict(Open=[100],High=[102],Low=[99],Close=[101],Volume=[5]),index=idx)
    normalized=normalize_history(frame,3600,now,'stocks',cal)
    assert normalized[0]['end']==pd.Timestamp('2026-11-27T18:00:00Z').timestamp()
    assert normalize_history(frame,3600,pd.Timestamp('2026-11-27T17:59:00Z').timestamp(),'stocks',cal)==[]


def test_collector_metadata_missing_does_not_synthesize_quote(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from entrydesk.data import collect_symbol
    calls=[]
    class Fake:
        def __init__(self,symbol):
            self._price_history=type('Metadata',(),{'_history_metadata':{'currency':'USD','regularMarketPrice':100}})()
        def history(self,**kwargs):
            calls.append(kwargs)
            return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])
    monkeypatch.setattr(yf,'Ticker',Fake)
    now=pd.Timestamp('2026-10-03T12:00:00Z').timestamp()
    b=collect_symbol('SPY','stocks',now)
    assert b['quote'] is None and not b['market_open']
    assert calls[0]['end']-calls[0]['start']==729*86400
    assert calls[0]['timeout']==8
    f=collect_symbol('GC=F','commodities',now)
    assert not f['market_open'] and f['contract_kind']=='continuous_future_unverified'


def test_pinned_source_parity_when_checkout_available():
    import ast
    import pathlib
    import subprocess
    source=pathlib.Path('/Users/perry/Documents/Code/astra-quant-agent')
    if not source.is_dir(): pytest.skip('optional upstream checkout absent')
    pin='78c0e4aa768511e888c392aa27de357b02aaf0f4'
    upstream=subprocess.check_output(['git','-C',str(source),'show',f'{pin}:scripts/factors/okx_quant_factors.py'],text=True)
    names={'macd_series','detect_divergence','classify_macd_momentum_state','compute_macd_factors'}
    tree=ast.parse(upstream)
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    from entrydesk.astra.math_utils import safe_float
    namespace=dict(_sf=safe_float,MACD_FAST=12,MACD_SLOW=26,MACD_SIGNAL=9,DIVERGENCE_LOOKBACK=20)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+selected,type_ignores=[])),'upstream','exec'),namespace)
    from entrydesk.astra.calculations import compute_macd_factors
    values=[100+i*.2+math.sin(i)*3 for i in range(100)]
    assert compute_macd_factors(values,values[-1])==namespace['compute_macd_factors'](values,values[-1])
    scoring=subprocess.check_output(['git','-C',str(source),'show',f'{pin}:scripts/factors/scoring.py'],text=True)
    ns={}; exec(scoring,ns)
    for f in [build_factors(bars(),[]),build_factors(bars(constant=True),bars(step=900))]:
        a=copy.deepcopy(f); b=copy.deepcopy(f)
        assert score_composite_alpha(a)==ns['score_composite_alpha'](b)
        assert a==b


def test_actual_yahoo_formatted_observation_timestamp_preserved(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from entrydesk.data import collect_symbol
    observed=pd.Timestamp('2026-10-02T15:00:00Z')
    class Fake:
        def __init__(self,symbol):
            self._price_history=type('Metadata',(),{'_history_metadata':{'currency':'USD','regularMarketPrice':100,'regularMarketTime':observed}})()
        def history(self,**kwargs):
            return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])
    monkeypatch.setattr(yf,'Ticker',Fake)
    b=collect_symbol('BTC-USD','crypto',observed.timestamp()+120)
    assert b['quote']==dict(price=100,time=observed.timestamp(),bid=None,ask=None)


def test_finite_inputs_that_overflow_calculation_fail_closed():
    huge=bars(20,900)
    for b in huge:
        b.update(open=1e308,high=1.1e308,low=9e307,close=1e308,volume=1e308)
    with pytest.raises(ValueError): build_factors(bars(),huge)


def test_quote_reward_risk_overflow_is_not_valid_geometry():
    assert not validate_quote('BUY_LONG',1e-200,1e308,5e-201)[0]


def test_rsi_divergence_exact_prefix_reference_and_bounded_work(monkeypatch):
    import random
    import time
    from entrydesk.astra.calculations import classify_rsi_zone, detect_divergence
    import entrydesk.factors as adapter
    def reference(one, fifteen, trend):
        def scalar(values, rounded=False):
            if len(values)<15: return None
            diffs=[float(values[i])-float(values[i-1]) for i in range(1,len(values))]
            gain=sum(max(d,0.0) for d in diffs[-14:])/14
            loss=sum(max(-d,0.0) for d in diffs[-14:])/14
            value=100-100/(1+gain/loss) if loss else (100.0 if gain else 50.0)
            return round(value,1) if rounded else value
        rsi=scalar(one,True)
        series=[scalar(one[:end]) for end in range(15,len(one)+1)]
        return dict(rsi_1h=rsi,rsi_15m=scalar(fifteen,True),rsi_zone=classify_rsi_zone(rsi,trend),
                    rsi_divergence=detect_divergence(one,series) if series else 'INSUFFICIENT_DATA')
    randomizer=random.Random(391)
    for length in list(range(45))+[100,350]:
        for values in [[100.0]*length, [100.0+i for i in range(length)], [100.0+randomizer.uniform(-10,10) for _ in range(length)]]:
            for trend in ['RANGE','BULL','BEAR']:
                assert compute_rsi_factors(values,values[-18:],trend)==reference(values,values[-18:],trend)
    b=bars(100)
    expected=adapter.build_factors(b,bars(20,900))
    monkeypatch.setattr(adapter,'compute_rsi_factors',reference)
    assert adapter.build_factors(b,bars(20,900))==expected
    start=time.perf_counter()
    compute_rsi_factors([100.0+math.sin(i) for i in range(8000)],[],'RANGE')
    assert time.perf_counter()-start<.5, 'RSI only needs the last20 divergence samples, not every prefix'
