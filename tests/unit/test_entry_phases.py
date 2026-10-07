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
