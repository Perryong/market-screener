"""End-to-end candle strategy and chronological evidence, without factor mocks."""
import copy
import pytest
from entrydesk.factors import build_factors
from entrydesk import validation


def trend_bars(side='LONG', count=120):
    sign=1 if side=='LONG' else -1
    bars=[]
    for i in range(count):
        opening=100+sign*i*.15
        close=opening+sign*.15
        bars.append(dict(start=i*3600,end=(i+1)*3600,open=opening,high=max(opening,close)+.2,
                         low=min(opening,close)-.2,close=close,volume=100))
    last=bars[-1]; last['close']+=sign*2; last['volume']=400
    last['high']=max(last['open'],last['close'])+.2;last['low']=min(last['open'],last['close'])-.2
    return bars


def quarters(bars):
    result=[]
    for b in bars:
        for j in range(4):
            opening=b['open']+(b['close']-b['open'])*j/4
            closing=b['open']+(b['close']-b['open'])*(j+1)/4
            result.append(dict(start=b['start']+j*900,end=b['start']+(j+1)*900,open=opening,
                high=max(opening,closing)+.05,low=min(opening,closing)-.05,close=closing,volume=b['volume']/4))
    return result


@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_real_completed_candles_can_trigger_without_full_factor_score(side):
    bars=trend_bars(side); factors=build_factors(bars,[])
    assert abs(factors['composite_alpha_score'])<45  # The previous impossible gate.
    assert validation.pattern(bars,factors)==side
    close=bars[-1]['close']; sign=1 if side=='LONG' else -1
    future=dict(start=bars[-1]['end'],end=bars[-1]['end']+3600,open=close,
        high=close+4,low=close-4,close=close+sign,volume=100)
    result=validation.backtest(bars+[future], 'crypto', quarters(bars+[future]))
    directional=result if side=='LONG' else result['short_research']
    trades=directional['train']['trade_log']+directional['holdout']['trade_log']
    assert len(trades)==1
    assert trades[0]['side']==side and trades[0]['entry_time']==future['start']
    assert result['strategy_id']==validation.STRATEGY_ID
    assert result['rule_coverage']['confirmation_15m_replayed'] is True


def test_context_score_cannot_substitute_for_missing_or_opposed_factors():
    bars=trend_bars()
    assert validation.pattern(bars,{'signal_recommendation':'BUY_LONG','composite_alpha_score':90}) is None
    f=build_factors(bars,[]); f['trend_momentum']['macd_hist']=-1
    assert validation.pattern(bars,f) is None
    f['trend_momentum']['macd_hist']=1;f['trend_momentum']['adx_1h']=21.99
    assert validation.pattern(bars,f) is None


def test_confirmation_uses_signal_time_and_ignores_future_quarters():
    bars=trend_bars(); q=quarters(bars)
    assert validation.confirmation(bars,q,'LONG')
    assert not validation.confirmation(bars,q,None)
    future=dict(q[-1],start=bars[-1]['end'],end=bars[-1]['end']+900,close=1,low=1)
    assert validation.confirmation(bars,q+[future],'LONG')
    assert not validation.confirmation(bars,q[:-1]+[future],'LONG')
    changed=copy.deepcopy(q); changed[-1]['close']=1
    assert not validation.confirmation(bars,changed,'LONG')


def test_confirmed_replay_never_relabels_missing_15m_as_valid():
    result=validation.backtest(trend_bars(),'stocks',[])
    assert result['holdout']['trades']==0
    assert result['rule_coverage']['confirmation_15m_replayed'] is False
    assert not result['ready']
    assert result['strategy_scope']=='confirmed_trend_breakout'


def test_grouped_uncertainty_is_deterministic_and_requires_days_and_trades():
    assert validation.grouped_expectancy([])['interval'] is None
    crowded=[dict(exit_time=1000,net_r=1) for _ in range(40)]
    assert validation.grouped_expectancy(crowded)['interval'] is None
    samples=[dict(exit_time=i*86400+1000,net_r=1) for i in range(30)]
    result=validation.grouped_expectancy(samples)
    assert result==validation.grouped_expectancy(samples)
    assert result['interval']==[1,1] and result['days']==30
    assert result['block_days']==5 and result['replicates']==1000
    assert validation.grouped_expectancy([dict(t,net_r=-1) for t in samples])['interval']==[-1,-1]


def test_short_research_results_cannot_certify_long_entry_policy():
    bars=trend_bars('SHORT');close=bars[-1]['close']
    bars.append(dict(start=bars[-1]['end'],end=bars[-1]['end']+3600,open=close,high=close+.1,low=close-4,close=close-1,volume=100))
    result=validation.backtest(bars,'crypto',quarters(bars))
    assert result['train']['trades']+result['holdout']['trades']==0
    assert result['short_research']['train']['trades']+result['short_research']['holdout']['trades']==1
    assert not result['ready']


@pytest.mark.parametrize('bad',[None,[],{'trend_momentum':None},{'trend_momentum':[]},{'trend_momentum':{'adx_1h':True,'rsi_1h':60,'macd_hist':1}}])
def test_malformed_factor_blocks_do_not_become_a_direction(bad):
    if bad is None:  # None explicitly means the cheap price/volume prefilter.
        assert validation.pattern(trend_bars(),bad)=='LONG'
    else:
        assert validation.pattern(trend_bars(),bad) is None


def test_unfinished_training_trade_cannot_suppress_holdout_signal(monkeypatch):
    from entrydesk import factors
    bars=[dict(start=i*3600,end=(i+1)*3600,open=100,high=101,low=99,close=100,volume=100) for i in range(75)]
    bars[65].update(high=105,close=104,volume=300)
    for i in range(66,75):bars[i].update(open=104,high=104.1,low=103.9,close=104)
    bars[72].update(high=108,close=107,volume=300)
    bars[73].update(open=107,high=110,low=106.9,close=108)
    bars[74].update(open=108,high=108.1,low=107.9,close=108)
    monkeypatch.setattr(factors,'build_factors',lambda b,q:dict(trend_momentum=dict(adx_1h=30,rsi_1h=60,macd_hist=1),
        volatility_channel=dict(atr_1h=.5 if len(b)>=72 else 10)))
    result=validation.backtest(bars,'crypto',quarters(bars))
    assert result['split_index']==71
    assert result['holdout']['trades']==1
    assert result['holdout']['trade_log'][0]['entry_time']==73*3600
    assert result['holdout']['trade_log'][0]['net_r']==pytest.approx(2)


def test_watching_explains_missing_pattern_without_inventing_trade_levels():
    from entrydesk.signals import evaluate
    bars = trend_bars()
    bars[-1]['volume'] = 100  # Real breakout and momentum, insufficient volume.
    now = bars[-1]['end']
    result = evaluate(dict(symbol='BTC-USD', asset_class='crypto', source='yahoo',
                           bars_1h=bars, bars_15m=quarters(bars), quote=None), now)
    assert result['state'] == 'WATCHING'
    assert all(result[key] is None for key in ('entry', 'stop', 'target', 'net_rr'))
    evidence = result['setup_evidence']
    assert evidence['volume_ratio'] == 1
    assert evidence['breakout_high'] == pytest.approx(118.05)
    checks = {check['id']: check['passed'] for check in evidence['checks']}
    assert checks == dict(breakout=True, volume=False, adx=True, momentum=True,
                          confirmation=True, hourly_fresh=True, quote_fresh=False)


def test_stale_quote_reference_levels_have_cost_adjusted_rr_and_actual_timestamp():
    from entrydesk.signals import evaluate
    bars = trend_bars()
    now = bars[-1]['end'] + 121
    result = evaluate(dict(symbol='BTC-USD', asset_class='crypto', source='yahoo',
                           bars_1h=bars, bars_15m=quarters(bars),
                           quote=dict(price=120, time=now-121)), now)
    assert result['state'] == 'BLOCKED'
    assert result['entry'] is None and result['net_rr'] is None
    reference = result['reference_levels']
    assert reference['entry'] == 120
    assert reference['stop'] == pytest.approx(119.45)
    assert reference['net_rr'] == pytest.approx(2)
    assert reference['cost_per_side'] == .0015
    assert reference['signal_time'] == 432000
    assert result['setup_evidence']['quote_time'] == 432000
