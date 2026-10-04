"""Source units and dated fallback records survive research refreshes."""
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

import pytest

from screener import research, research_sources
from screener.runtime import Store


@pytest.mark.parametrize(('metric', 'unit'), [
    ('Diluted Average Shares', 'shares'),
    ('Basic Average Shares', 'shares'),
    ('Ordinary Shares Number', 'shares'),
    ('Preferred Shares Number', 'shares'),
    ('Treasury Shares Number', 'shares'),
    ('Share Issued', 'shares'),
    ('Tax Rate For Calcs', 'ratio'),
    ('Basic EPS', 'USD/share'),
    ('Diluted EPS', 'USD/share'),
    ('Number Of Employees', 'count'),
    ('Common Stock Issuance', 'USD'),
    ('Stock Based Compensation', 'USD'),
    ('Diluted NI Availto Com Stockholders', 'USD'),
    ('Effect Of Exchange Rate Changes', 'USD'),
    ('Total Revenue', 'USD'),
])
def test_collected_financial_units_do_not_turn_counts_into_money(metric, unit):
    settings = research.load_settings(None, ['HSBA.L'])
    financials = [{'metric': metric, 'value': 2.5, 'end': '2025-12-31', 'source': 'Yahoo Finance'}]
    def load(key, ttl, loader):
        if ':info:' in key:
            return {'currency': 'GBp', 'financialCurrency': 'USD', 'marketCap': 1000}
        if ':history:' in key:
            return [{'date': '2026-10-01', 'price': 1234, 'close': 1200, 'volume': 10, 'dividend': 20}]
        if ':financials:' in key:
            return financials
        return None
    settings['_load'] = load
    with patch.dict('os.environ', {'SEC_USER_AGENT': ''}):
        record = research_sources.collect_instrument('HSBA.L', settings, 1791072000)
    assert record['financials'][0]['unit'] == unit
    assert record['financials'][0]['value'] == 2.5
    assert (record['currency'], record['financial_currency'], record['price']) == ('GBP', 'USD', 12.34)
    assert record['metrics']['market_cap'] == 1000


@pytest.mark.parametrize('core_price', [None, 120])
def test_missing_detailed_quote_preserves_dated_previous_or_core_record(tmp_path, core_price):
    settings = research.load_settings(None, ['AAPL'])
    settings.update(funds=[], europe=[], proxies=[], discovery=False, api_sources=False)
    previous = {'symbol': 'AAPL', 'price': 100, 'as_of': '2026-09-30',
                'financials': [{'metric': 'Total Revenue', 'value': 1000, 'unit': 'USD'}]}
    core = {'symbol': 'AAPL', 'price': core_price, 'as_of': '2026-10-01' if core_price else None}
    detail = {'symbol': 'AAPL', 'price': None, 'as_of': None}
    store = Store(tmp_path / 'journal.sqlite3')
    try:
        store.put('research-snapshot', {'generated_at': 1790812800, 'instruments': [previous]})
        with ExitStack() as stack:
            for name in ('economy', 'releases', 'ipos', 'news'):
                stack.enter_context(patch.object(research_sources, 'collect_' + name, return_value=[]))
            stack.enter_context(patch.object(research_sources, 'collect_instrument', side_effect=[deepcopy(core), detail]))
            snapshot = research.refresh(store, settings, 1791072000)
        expected = previous if core_price is None else core
        assert snapshot['instruments'][0] == expected
        assert store.get('research-snapshot')['instruments'][0] == expected
    finally:
        store.close()
