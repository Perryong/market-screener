"""A fresh scheduler can publish observed stock history while the exchange is closed."""
from datetime import datetime

from screener import feeds, runtime


def test_weekend_initial_scan_publishes_closed_session_once(tmp_path, monkeypatch):
    now = datetime.fromisoformat('2026-10-04T12:00:00+00:00').timestamp()
    friday_close = datetime.fromisoformat('2026-10-02T20:00:00+00:00').timestamp()
    bars = [dict(start=friday_close-(60-i)*86400, end=friday_close-(59-i)*86400,
                 open=100, high=102, low=98, close=100, volume=100) for i in range(60)]
    config = runtime.default_config()
    config['stocks']['symbols'] = ['SPY']
    config['crypto']['enabled'] = False
    monday_open = datetime.fromisoformat('2026-10-05T13:30:00+00:00').timestamp()
    monkeypatch.setattr(feeds.MarketData, 'calendar', lambda self: [
        (friday_close-23400, friday_close), (monday_open, monday_open+23400)])
    monkeypatch.setattr(feeds.MarketData, 'stock', lambda self, symbol:
                        dict(symbol=symbol, market='stocks', source='recorded Yahoo',
                             setup=bars, hourly=bars, quote=None, market_open=False))
    store = runtime.Store(tmp_path/'journal.db')
    try:
        updates, errors = runtime.scan(store, config, now, scheduled=True)
        assert updates == 1 and errors == []
        assert store.get('job:stocks')['done'] == now
        assert store.get('job:stocks')['full_done'] == 0
        result = store.get('result:stocks:SPY')
        assert result['status'] == 'WATCHING'
        assert result['setup_close'] == friday_close
        assert result['quote'] is None and 'entry' not in result
        assert runtime.scan(store, config, now+3600, scheduled=True) == (0, [])
        assert store.get('result:stocks:SPY') == result
        assert runtime.scan(store, config, monday_open+5400, scheduled=True) == (1, [])
    finally:
        store.close()
