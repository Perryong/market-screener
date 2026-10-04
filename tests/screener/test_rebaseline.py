"""Explicit recovery from provider revisions retains the abandoned evidence."""
import copy

import pytest

from screener import engine, runtime
from screener.shared import DataError


def baseline(store):
    bars = [dict(start=i*3600, end=(i+1)*3600, open=100, high=102, low=98,
                 close=100, volume=100) for i in range(60)]
    bundle = dict(symbol='TEST', market='stocks', source='recorded provider',
                  setup=bars, hourly=copy.deepcopy(bars), quote=None,
                  market_open=False, regime='NEUTRAL')
    runtime.process(store, bundle, engine.DEFAULTS, runtime.default_config()['paper'], 216000)
    store.put('bundle:stocks:TEST', bundle)
    revised = copy.deepcopy(bundle)
    revised['setup'][-1]['volume'] = 101
    # This new breakout must become the baseline, never a replayed entry.
    revised['setup'].append(dict(start=216000, end=219600, open=100, high=105,
                                 low=99, close=104, volume=400))
    revised['hourly'] = copy.deepcopy(revised['setup'])
    return bundle, revised


def test_explicit_inactive_rebaseline_archives_evidence_without_replaying_breakout(tmp_path):
    store = runtime.Store(tmp_path/'test.db')
    try:
        original, revised = baseline(store)
        previous = store.get('signal:stocks:TEST')
        with pytest.raises(DataError, match='rebaseline required'):
            runtime.process(store, revised, engine.DEFAULTS, runtime.default_config()['paper'], 219600)
        result = runtime.process(store, revised, engine.DEFAULTS,
                                 runtime.default_config()['paper'], 219600, rebaseline_inactive=True)
        assert result['status'] not in engine.ACTIVE
        assert result['setup_close'] == 219600
        assert 'entry' not in result and store.trades() == []
        assert result['rebaseline']['previous_status'] == 'WATCHING'
        archive = store.get(result['rebaseline']['archive_key'])
        assert archive['signal'] == previous
        assert archive['bundle'] == original
        assert archive['reason'] == 'Missing/revised anchor; explicit rebaseline required'
        assert store.get('signal:stocks:TEST')['setup_end'] == 219600
    finally:
        store.close()


@pytest.mark.parametrize('protected', ['active_signal', 'OPEN', 'UNSCORABLE'])
def test_rebaseline_refuses_active_or_unresolved_exposure(tmp_path, protected):
    store = runtime.Store(tmp_path/'test.db')
    try:
        _, revised = baseline(store)
        if protected == 'active_signal':
            state = store.get('signal:stocks:TEST')
            store.put('signal:stocks:TEST', dict(state, status='CONFIRMED'))
        else:
            store.trade(dict(id='existing', key='stocks:TEST', status=protected))
        with pytest.raises(DataError, match='rebaseline required'):
            runtime.process(store, revised, engine.DEFAULTS,
                            runtime.default_config()['paper'], 219600, rebaseline_inactive=True)
        assert store.get('signal:stocks:TEST')['setup_end'] == 216000
        assert not store.db.execute("SELECT key FROM kv WHERE key LIKE 'rebaseline:%'").fetchall()
        if protected != 'active_signal':
            assert store.trades()[0]['id'] == 'existing'
            assert store.trades()[0]['status'] == 'UNSCORABLE'
    finally:
        store.close()


def test_scan_passes_explicit_rebaseline_option_and_preserves_closed_trades(tmp_path, monkeypatch):
    from screener import feeds
    store = runtime.Store(tmp_path/'test.db')
    try:
        _, revised = baseline(store)
        closed = dict(id='closed', key='stocks:TEST', symbol='TEST', market='stocks', currency='USD',
                      status='CLOSED', entry=100, entry_at=200000, stop=98, target=104, quantity=1,
                      last_end=216000, cost_bps=10, slippage_bps=5, regime='NEUTRAL',
                      exit=104, exit_at=216000, exit_reason='TARGET', pnl=3.9)
        store.trade(closed)
        config = runtime.default_config()
        config['stocks']['symbols'] = ['TEST']
        config['crypto']['enabled'] = False
        monkeypatch.setattr(feeds.MarketData, 'calendar', lambda self: [])
        monkeypatch.setattr(feeds.MarketData, 'stock', lambda self, symbol: copy.deepcopy(revised))
        assert runtime.scan(store, config, 219600, rebaseline_inactive=True) == (1, [])
        assert store.get('result:stocks:TEST')['rebaseline']['previous_status'] == 'WATCHING'
        assert store.trades() == [closed]
    finally:
        store.close()


def test_rebaseline_does_not_accept_changed_source_identity(tmp_path):
    store = runtime.Store(tmp_path/'test.db')
    try:
        _, revised = baseline(store)
        revised['source'] = 'different provider'
        with pytest.raises(DataError, match='Feed or strategy changed'):
            runtime.process(store, revised, engine.DEFAULTS,
                            runtime.default_config()['paper'], 219600, rebaseline_inactive=True)
        assert store.get('signal:stocks:TEST')['setup_end'] == 216000
        assert not store.db.execute("SELECT key FROM kv WHERE key LIKE 'rebaseline:%'").fetchall()
    finally:
        store.close()
