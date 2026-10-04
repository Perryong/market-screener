"""Offline research boundaries: stale data, calculations and public-source parsing."""
import importlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from screener.runtime import Store


class ResearchTest(unittest.TestCase):
    def test_resource_expiry_metadata_survives_cache_and_failure(self):
        research=self.module()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'journal.sqlite3')
            try:
                first=research.cached_resource(store,'Feed:test',60,100,lambda:['headline'])
                cached=research.cached_resource(store,'Feed:test',60,110,lambda: self.fail('fresh cache fetched again'))
                def fail():
                    raise ValueError('offline')
                stale=research.cached_resource(store,'Feed:test',60,200,fail)
                for row in (first,cached,stale):
                    self.assertEqual(row.get('max_age_seconds'),60)
                    self.assertEqual(row['fetched_at'],100)
                self.assertEqual(stale['status'],'stale')
            finally:
                store.close()

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('screener.research'), 'Research collection must exist')
        return importlib.import_module('screener.research')

    def test_cache_retains_original_timestamp_on_failure(self):
        research = self.module()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'journal.sqlite3')
            try:
                first = research.cached_resource(store, 'test', 10, 1, lambda: {'price': 100})
                def fail():
                    raise ValueError('Provider unavailable')
                second = research.cached_resource(store, 'test', 10, 20000, fail)
                self.assertEqual(first['status'], 'ok')
                self.assertEqual(second['data'], {'price': 100})
                self.assertEqual(second['fetched_at'], 1)
                self.assertEqual(second['status'], 'stale')
                absent = research.cached_resource(store, 'absent', 10, 20000, fail)
                self.assertIsNone(absent['data'])
                self.assertEqual(absent['status'], 'unavailable')
            finally:
                store.close()

    def test_invalid_settings_rejected(self):
        research = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            for invalid in ({'funds':['SPY','SPY']}, {'max_requests':0},
                            {'feeds':[{'url':'file:///private','name':'bad'}]}):
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    research.load_settings(path, ['AAPL'])

    def test_nonfinite_values_are_missing_not_zero(self):
        research = self.module()
        self.assertIsNone(research.finite(float('nan')))
        self.assertIsNone(research.finite(float('inf')))
        self.assertIsNone(research.finite(True))
        self.assertEqual(research.finite('12.5'), 12.5)

    def test_returns_require_full_history_and_preserve_common_dates(self):
        research = self.module()
        self.assertTrue(hasattr(research, 'returns'), 'Research return calculations must exist')
        values = research.returns([{'date':'2026-09-01','close':100}, {'date':'2026-09-02','close':110}], '2026-09-02')
        self.assertAlmostEqual(values['day'], 0.10)
        self.assertIsNone(values['year'])
        self.assertIsNone(values['annualized'])

    def test_invalid_ratio_is_unavailable(self):
        research = self.module()
        self.assertTrue(hasattr(research, 'ratio'), 'Ratios must validate denominators')
        self.assertIsNone(research.ratio(10,-2))
        self.assertIsNone(research.ratio(10,0))
        self.assertEqual(research.ratio(10,20),0.5)

    def test_sec_facts_keep_period_currency_and_source(self):
        self.assertIsNotNone(importlib.util.find_spec('screener.research_sources'))
        sources = importlib.import_module('screener.research_sources')
        facts = {'facts':{'us-gaap':{'Revenues':{'units':{'USD':[
            {'start':'2024-01-01','end':'2024-12-31','val':100,'form':'10-K','filed':'2025-02-01','accn':'123','fy':2024},
            {'start':'2024-01-01','end':'2024-03-31','val':25,'form':'10-Q','filed':'2024-05-01','accn':'456','fy':2024}]}}}}}
        record = sources.sec_facts(facts)[0]
        self.assertEqual(record['value'],100)
        self.assertEqual(record['unit'],'USD')
        self.assertEqual(record['end'],'2024-12-31')
        self.assertEqual(record['accession'],'123')

    def test_partial_fund_holdings_are_not_renormalized(self):
        self.assertIsNotNone(importlib.util.find_spec('screener.research_sources'))
        sources = importlib.import_module('screener.research_sources')
        rows = sources.normalize_holdings([{'symbol':'AAPL','weight':0.30}, {'symbol':'BAD','weight':float('nan')}])
        self.assertEqual(rows,[{'symbol':'AAPL','weight':0.30,'name':'AAPL'}])

    def test_yahoo_yield_units_and_future_dividend_amount(self):
        sources=importlib.import_module('screener.research_sources')
        research=self.module()
        settings=research.load_settings(None,['AAPL'])
        def load(key,ttl,loader):
            if ':info:' in key:
                return {'currency':'USD','dividendYield':0.32,'lastDividendValue':0.25}
            if ':history:' in key:
                return [{'date':'2026-01-01','price':100,'close':100,'volume':100,'dividend':0}]
            return None
        settings['_load']=load
        row=sources.collect_instrument('AAPL',settings,1)
        self.assertEqual(row['metrics']['dividend_yield'],0.0032)

    def test_http_transport_keeps_verified_tls_and_bounded_response(self):
        import ssl,urllib.error,subprocess
        from unittest.mock import Mock
        sources=importlib.import_module('screener.research_sources')
        failure=urllib.error.URLError(ssl.SSLCertVerificationError('local trust missing'))
        opener=Mock();opener.open.side_effect=failure
        def run(args,**kwargs):
            self.assertNotIn('--insecure',args)
            self.assertIn('--max-filesize',args)
            return subprocess.CompletedProcess(args,0,b'date,value\n2026-01-01,3.5',b'')
        with patch.object(sources.sys,'platform','darwin'),patch.object(sources,'build_opener',return_value=opener),patch.object(sources.subprocess,'run',side_effect=run):
            self.assertEqual(sources.read_text('https://example.com/feed'),'date,value\n2026-01-01,3.5')

    def test_pence_prices_normalize_without_scaling_market_cap(self):
        sources=importlib.import_module('screener.research_sources')
        settings=self.module().load_settings(None,['HSBA.L'])
        settings['_core_only']=True
        settings['_load']=lambda key,ttl,loader: {'currency':'GBp','financialCurrency':'USD','marketCap':1000} if ':info:' in key else [{'date':'2026-01-01','price':1234,'close':1200,'volume':10,'dividend':20}]
        row=sources.collect_instrument('HSBA.L',settings,1)
        self.assertEqual((row['currency'],row['price'],row['metrics']['market_cap']),('GBP',12.34,1000))
        self.assertEqual(row['history'][0]['dividend'],.2)
        self.assertEqual(row['financial_currency'],'USD')

    def test_reported_earnings_keep_exchange_timezone(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import Mock
        sources=importlib.import_module('screener.research_sources')
        frame=Mock()
        frame.iterrows.return_value=[(datetime(2026,10,1,16,30,tzinfo=ZoneInfo('America/New_York')),{'Reported EPS':1.2,'EPS Estimate':1.1})]
        rows=sources.earnings_records(frame,2000000000)
        self.assertEqual(rows[0]['status'],'reported')
        self.assertEqual((rows[0]['time'],rows[0]['timezone']),('16:30','America/New_York'))

    def test_macro_missing_observations_and_transformation(self):
        sources = importlib.import_module('screener.research_sources')
        self.assertTrue(hasattr(sources,'parse_macro'))
        records=sources.parse_macro('observation_date,TEST\n2025-01-01,100\n2026-01-01,110\n2026-02-01,.\n', 'yoy')
        self.assertEqual(records[-1],{'date':'2026-02-01','value':None})
        self.assertAlmostEqual(records[-2]['value'],10)
        self.assertEqual(sources.parse_macro('DATE,TEST\n2026-01-01,3.2\n','level')[0]['value'],3.2)

    def test_feed_deduplicates_and_rejects_unsafe_urls(self):
        sources=importlib.import_module('screener.research_sources')
        self.assertTrue(hasattr(sources,'parse_feed'))
        xml='<rss><channel><item><title>Market news</title><link>https://example.com/a?utm_source=x</link><description>&lt;b&gt;Facts&lt;/b&gt;</description></item><item><title>Market news</title><link>https://example.com/a</link></item><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>'
        rows=sources.parse_feed(xml,{'name':'Publisher','category':'Markets'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url'],'https://example.com/a')
        self.assertEqual(rows[0]['excerpt'],'Facts')
        changed=sources.parse_feed('<rss><channel><item><title>New</title><link>https://example.com/new</link></item><item><title>Market news</title><link>https://example.com/a</link></item></channel></rss>',{'name':'Publisher'})
        self.assertEqual(rows[0]['id'],changed[1]['id'])

    def test_release_timezone_preserved(self):
        sources=importlib.import_module('screener.research_sources')
        self.assertTrue(hasattr(sources,'parse_ics'))
        rows=sources.parse_ics('BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=America/New_York:20261002T083000\nSUMMARY:Employment report\nEND:VEVENT\nEND:VCALENDAR', 'BLS','https://www.bls.gov/schedule/')
        self.assertEqual(rows[0]['date'],'2026-10-02')
        self.assertEqual(rows[0]['time'],'08:30')
        self.assertEqual(rows[0]['timezone'],'America/New_York')

    def test_registration_is_not_a_confirmed_ipo(self):
        sources=importlib.import_module('screener.research_sources')
        self.assertTrue(hasattr(sources,'normalize_ipos'))
        rows=sources.normalize_ipos({'data':{'filed':{'rows':[{'companyName':'Example','proposedTickerSymbol':'EX','filedDate':'10/01/2026'}]}}})
        self.assertEqual(rows[0]['status'],'filed')
        self.assertEqual(rows[0]['date'],'2026-10-01')

    def test_research_demo_publishes_without_network(self):
        research=self.module()
        self.assertTrue(hasattr(research,'demo_snapshot'))
        from screener.__main__ import main
        with tempfile.TemporaryDirectory() as directory, patch('screener.research_sources.read_text',side_effect=AssertionError('Network forbidden')), patch('yfinance.Ticker',side_effect=AssertionError('Network forbidden')):
            result=main(['research-demo','--state-dir',directory])
            self.assertEqual(result,0)
            snapshot=json.loads((Path(directory)/'public/research.json').read_text())
            self.assertEqual(snapshot['mode'],'demo')
            self.assertGreater(len(snapshot['instruments']),10)
            self.assertTrue(snapshot['news'])
            self.assertTrue(snapshot['economy'])
            self.assertIn('SYNTHETIC RESEARCH DEMO',(Path(directory)/'public/index.html').read_text())

    def test_publish_reuses_saved_research_and_exports_no_private_cache(self):
        research=self.module()
        self.assertTrue(hasattr(research,'demo_snapshot'))
        from screener.__main__ import publish
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'journal.sqlite3')
            try:
                store.put('research-snapshot',research.demo_snapshot(1000000000))
                store.put('research-cache:private',{'token':'NEVER_EXPORT'})
                with patch('screener.research_sources.read_text',side_effect=AssertionError('Network forbidden')):
                    publish(store,Path(directory)/'public','demo',1000000000)
                output=(Path(directory)/'public/index.html').read_text()
                self.assertNotIn('NEVER_EXPORT',output)
                self.assertIn('Research, Markets',output)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
