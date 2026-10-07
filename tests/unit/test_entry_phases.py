from entrydesk.phases import phases
from entrydesk.validation import backtest, futures_unverified
from entrydesk.signals import evaluate

H = 3600


def bar(t, c, spread=1.0, v=100):
    return dict(start=t, end=t + H, open=c, high=c + spread, low=c - spread, close=c, volume=v)


def checks(breakout=True, volume=True, adx=True, momentum=True, confirmation=True, hourly_fresh=True,
           quote_fresh=True):
    return [dict(id=k, passed=v) for k, v in locals().items()]


def test_h4_trend_up_from_rising_hourly_bars():
    bars = [bar(i * H, 1000 + 2 * i) for i in range(240)]
    h4 = phases(bars, checks(), 'LONG', True)['h4']
    assert h4['phase'] == 'TREND_UP'
    assert h4['adx'] >= 20


def test_h4_range_from_oscillating_bars():
    bars = [bar(i * H, 1000 + (10 if (i // 8) % 2 else -10)) for i in range(240)]
    assert phases(bars, checks(), None, False)['h4']['phase'] == 'RANGE'


def test_h4_unknown_without_enough_history():
    bars = [bar(i * H, 1000 + i) for i in range(40)]
    assert phases(bars, checks(), None, False)['h4']['phase'] == 'UNKNOWN'


def test_h4_ignores_unfinished_bucket():
    bars = [bar(i * H, 1000 + 2 * i) for i in range(242)]  # last bucket holds only 2 of 4 hours
    h4 = phases(bars, checks(), 'LONG', True)['h4']
    assert h4['bar_end'] == 240 * H


def test_h1_and_m15_ready_when_everything_lines_up():
    p = phases([], checks(), 'LONG', True)
    assert (p['h1']['phase'], p['m15']['phase']) == ('BREAKOUT_LONG', 'READY')
    assert p['h1']['passed'] == p['h1']['total'] == 4


def test_m15_confirmed_without_executable_entry():
    assert phases([], checks(), 'LONG', False)['m15']['phase'] == 'CONFIRMED'


def test_m15_unconfirmed_and_expired():
    assert phases([], checks(confirmation=False), 'SHORT', False)['m15']['phase'] == 'UNCONFIRMED'
    assert phases([], checks(hourly_fresh=False), 'SHORT', False)['m15']['phase'] == 'EXPIRED'


def test_unqualified_breakout_waits():
    p = phases([], checks(volume=False), None, False)
    assert (p['h1']['phase'], p['m15']['phase']) == ('BREAKOUT_UNQUALIFIED', 'WAIT')
    p = phases([], checks(breakout=False), None, False)
    assert (p['h1']['phase'], p['m15']['phase']) == ('NO_SETUP', 'WAIT')


def test_gold_is_the_only_verified_futures_proxy():
    assert not futures_unverified('commodities', 'GC=F')
    assert futures_unverified('commodities', 'SI=F')
    assert not futures_unverified('stocks', 'SPY')
    hourly = [bar(i * H, 1000 + i) for i in range(80)]
    assert backtest(hourly, 'commodities', [], 'GC=F')['exploratory'] is False
    assert backtest(hourly, 'commodities', [], 'SI=F')['exploratory'] is True


def test_evaluate_publishes_phases_and_gold_label():
    bars = [bar(i * H, 1000 + i) for i in range(80)]
    now = bars[-1]['end'] + 60
    gold = evaluate(dict(symbol='GC=F', asset_class='commodities', source='yahoo', bars_1h=bars, bars_15m=[]), now)
    assert gold['label'] == 'XAUUSD (GC=F proxy)'
    assert set(gold['phases']) == {'h4', 'h1', 'm15'}
    assert not any('continuous futures' in r for r in gold['reasons'])


def m15(t, c):
    return dict(start=t, end=t + 900, open=c, high=c + .5, low=c - .5, close=c, volume=10)


def test_charts_cap_lengths_and_use_completed_bars_only():
    from entrydesk.phases import charts
    hourly = [bar(i * H, 1000 + i) for i in range(402)]  # last 4h bucket unfinished
    quarter = [m15(i * 900, 1000 + i / 4) for i in range(402 * 4)]
    c = charts(hourly, quarter, {})
    assert (len(c['m15']['close']), len(c['h1']['close']), len(c['h4']['close'])) == (96, 120, 90)
    assert c['h1']['times'][-1] == hourly[-1]['end'] and c['m15']['times'][-1] == quarter[-1]['end']
    assert c['h4']['times'][-1] == 400 * H
    assert len(c['h4']['ema20']) == 90


def test_chart_levels_match_phases_and_trade_levels():
    from entrydesk.phases import charts
    hourly = [bar(i * H, 1000 + i) for i in range(240)]
    c = charts(hourly, [], dict(entry=1240, stop=1230, target=1265))
    h4 = phases(hourly, checks(), 'LONG', True)['h4']
    assert c['h4']['levels'] == dict(range_high=h4['range_high'], range_low=h4['range_low'])
    prior = hourly[-21:-1]
    assert c['h1']['levels'] == dict(range_high=max(b['high'] for b in prior), range_low=min(b['low'] for b in prior))
    assert c['m15']['levels'] == dict(c['h1']['levels'], entry=1240, stop=1230, target=1265)


def test_only_gold_carries_charts():
    bars = [bar(i * H, 1000 + i) for i in range(80)]
    now = bars[-1]['end'] + 60
    gold = evaluate(dict(symbol='GC=F', asset_class='commodities', source='yahoo', bars_1h=bars, bars_15m=[]), now)
    spy = evaluate(dict(symbol='SPY', asset_class='stocks', source='yahoo', bars_1h=bars, bars_15m=[]), now)
    assert set(gold['charts']) == {'m15', 'h1', 'h4'}
    assert 'charts' not in spy
