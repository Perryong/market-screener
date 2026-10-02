import math
import pytest
from entrydesk.validation import simulate_trade, readiness, backtest
from entrydesk.signals import evaluate


def bar(t, o=100, h=102, l=98, c=100, v=100):
    return dict(start=t, end=t+3600, open=o, high=h, low=l, close=c, volume=v)


def test_gap_ambiguity_costs():
    stop = simulate_trade([bar(0, 100, 110, 90), bar(3600)], 0, 'LONG', 2, 'stocks')
    assert stop['exit_reason'] == 'stop' and stop['net_r'] < -1
    gap = simulate_trade([bar(0, l=99), bar(3600, 95, 96, 94, 95)], 0, 'LONG', 2, 'stocks')
    assert gap['exit'] == 95 and gap['net_r'] < -2.5


def test_readiness_requires_genuine_forward_evidence():
    metrics = dict(trades=30, expectancy=0.2, profit_factor=1.2, max_drawdown=0.1)
    assert not readiness({'holdout': metrics})[0]
    assert not readiness({'holdout': {**metrics, 'expectancy': math.nan}, 'forward_paper': metrics})[0]


def test_invalid_bars_fail_closed():
    with pytest.raises(ValueError):
        backtest([bar(0, c=float('nan'))], 'stocks')
    result = evaluate({'symbol': 'X', 'asset_class': 'stocks', 'bars_1h': []}, 10000)
    assert result['state'] == 'BLOCKED'


def test_next_open_and_prefix_invariance(monkeypatch):
    import entrydesk.factors as factors
    monkeypatch.setattr(factors, 'build_factors', lambda bars, confirm: {
        'signal_recommendation': 'BUY_LONG', 'volatility_channel': {'atr_1h': 2}})
    bars = [bar(i*3600, h=101, l=99) for i in range(60)]
    bars[-1] = bar(59*3600, h=104, l=99, c=103, v=300)
    bars += [bar(60*3600, o=104, h=110, l=103, c=106)]
    first = backtest(bars, 'stocks')
    trade = (first['train']['trade_log'] + first['holdout']['trade_log'])[0]
    assert trade['entry'] == 104 and trade['entry_time'] == 60*3600
    extended = backtest(bars + [bar(i*3600) for i in range(61, 80)], 'stocks')
    assert trade == (extended['train']['trade_log'] + extended['holdout']['trade_log'])[0]


def test_quote_confirmation_market_and_futures_gates(monkeypatch):
    import entrydesk.factors as factors
    monkeypatch.setattr(factors, 'build_factors', lambda bars, confirm: {
        'signal_recommendation': 'BUY_LONG', 'volatility_channel': {'atr_1h': 2}, 'composite_alpha_score': 70})
    bars = [bar(i*3600, h=101, l=99) for i in range(60)]
    bars[-1] = bar(59*3600, h=104, l=99, c=103, v=300)
    now = 60*3600
    bundle = dict(symbol='X', asset_class='stocks', source='yahoo', bars_1h=bars,
                  bars_15m=[], market_open=False, quote=dict(price=103, time=now-121, bid=102.99, ask=103.01))
    result = evaluate(bundle, now)
    assert result['state'] == 'BLOCKED'
    assert any('confirmation' in r for r in result['reasons'])
    assert any('quote' in r for r in result['reasons'])
    assert any('market closed' in r for r in result['reasons'])
    bundle.update(asset_class='commodities')
    assert any('contract' in r for r in evaluate(bundle, now)['reasons'])


def test_no_fabricated_terminal_close():
    assert simulate_trade([bar(0, h=101, l=99)], 0, 'LONG', 2, 'stocks') is None


def test_closed_paper_records_and_holdout_pass():
    metrics = dict(trades=30, expectancy=.2, profit_factor=1.2, max_drawdown=.1)
    records = [dict(origin='forward_paper', closed=True, entry_time=i*2, exit_time=i*2+1, net_r=.2) for i in range(30)]
    assert readiness(dict(holdout=metrics, forward_paper=dict(closed_trades=records)))[0]
    records[-1]['net_r'] = float('nan')
    assert not readiness(dict(holdout=metrics, forward_paper=dict(closed_trades=records)))[0]


def test_net_target_covers_large_cost_cross_term():
    from entrydesk.validation import target_price
    for side in ('LONG', 'SHORT'):
        sign = 1 if side == 'LONG' else -1
        entry, risk, cost = 100, 20, .0015
        stop = entry - sign*risk
        target = target_price(entry, risk, side, cost)
        net_risk = risk + cost*(entry+stop)
        net_reward = sign*(target-entry)-cost*(entry+target)
        assert net_reward/net_risk >= 2-1e-12


def test_zero_volume_baseline_is_not_confirmation():
    from entrydesk.validation import pattern
    bars = [bar(i*3600, v=0) for i in range(60)]
    bars[-1] = bar(59*3600, h=104, c=103, v=300)
    assert pattern(bars, {'signal_recommendation': 'BUY_LONG'}) is None


def test_commodity_warning_preserves_real_history(tmp_path, monkeypatch):
    import json
    import subprocess
    import entrydesk.__main__ as cli
    bundle = dict(symbol='GC=F', asset_class='commodities', source='yahoo', bars_1h=[bar(0)],
                  bars_15m=[], errors=['continuous futures contract unverified'], quote=None)
    def fake_run(args, **kwargs):
        output = backtest(bundle['bars_1h'], 'commodities') if kwargs.get('input') else bundle
        return subprocess.CompletedProcess(args, 0, json.dumps(output), '')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    code = cli.main(['collect', '--symbols', 'GC=F', '--history-dir', str(tmp_path/'history'),
                     '--output', str(tmp_path/'out.json')])
    assert code == 1
    assert json.loads((tmp_path/'history/GC_F.json').read_text())['bars_1h'] == bundle['bars_1h']
    payload = json.loads((tmp_path/'out.json').read_text())
    assert payload['validation']['GC=F']['exploratory'] is True

