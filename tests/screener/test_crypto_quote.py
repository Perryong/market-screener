"""A missing live quote must not discard valid completed crypto candles."""
import pytest

from screener import engine, feeds, runtime
from screener.shared import DataError


def test_crypto_quote_failure_preserves_setup_but_blocks_entry(monkeypatch):
    now = 100 * 14400

    def response(url, params):
        if url.endswith('/ticker/24hr'):
            raise DataError('HTTP request failed')
        duration = {'4h': 14400, '1h': 3600}[params['interval']]
        return [[start * 1000, '100', '102', '98', '100', '100',
                 (start + duration) * 1000 - 1]
                for start in range(now - 60 * duration, now, duration)]

    monkeypatch.setattr(feeds, 'get_json', response)
    bundle = feeds.MarketData(runtime.default_config(), {}, now).crypto('BTCUSDT')
    assert len(bundle['setup']) == len(bundle['hourly']) == 60
    assert bundle['quote'] is None
    assert 'entries blocked' in bundle['quote_error']
    bundle['regime'] = 'NEUTRAL'
    result, _, _ = engine.evaluate(bundle, None, engine.DEFAULTS, now)
    assert result['status'] == 'WATCHING'
    metrics, reasons = engine.entry_check({'retest_end': now}, bundle, engine.DEFAULTS, now)
    assert metrics == {} and reasons == ['QUOTE_UNAVAILABLE']


@pytest.mark.parametrize('quote', [None, {}, {'lastPrice': 'nan', 'closeTime': 1440000000},
                                  {'lastPrice': '-1', 'closeTime': 1440000000}])
def test_malformed_crypto_quote_is_not_published(quote, monkeypatch):
    now = 100 * 14400
    cache = {'binance:BTCUSDT:' + interval: {'end': now, 'rows': [
        {'start': now-duration, 'end': now, 'open': 100, 'high': 102,
         'low': 98, 'close': 100, 'volume': 100}]}
        for interval, duration in [('4h', 14400), ('1h', 3600)]}
    monkeypatch.setattr(feeds, 'get_json', lambda url, params: quote)
    bundle = feeds.MarketData(runtime.default_config(), cache, now).crypto('BTCUSDT')
    assert bundle['quote'] is None
    assert 'entries blocked' in bundle['quote_error']
