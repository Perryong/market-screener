"""Regression coverage for public calendar dates and source provenance."""
import json
from datetime import date, datetime, timezone
from unittest.mock import patch

from screener import research_sources as sources
from screener.research import load_settings


def test_withdrawals_use_withdraw_date_and_proposed_exchange():
    rows = sources.normalize_ipos({'data': {'withdrawn': {'rows': [{
        'dealID': '123', 'companyName': 'Example', 'proposedTickerSymbol': 'EX',
        'proposedExchange': 'NASDAQ Global', 'filedDate': '7/10/2026',
        'withdrawDate': '9/25/2026',
    }]}}})
    assert rows[0]['date'] == '2026-09-25'
    assert rows[0]['exchange'] == 'NASDAQ Global'
    assert rows[0]['status'] == 'withdrawn'


def test_ipo_calendar_spans_year_boundary_and_deduplicates_events():
    def read(url, headers=None):
        month = url.rsplit('=', 1)[-1]
        rows = [{'dealID': '123', 'companyName': 'Example',
                 'proposedTickerSymbol': 'EX', 'expectedPriceDate': '01/20/2026'}]
        data = {'upcoming': {'rows': rows}}
        if month == '2025-12':
            data['priced'] = {'rows': [{'dealID': '122', 'companyName': 'Recent',
                                       'pricedDate': '12/30/2025'}]}
        if month == '2026-02':
            data['upcoming']['rows'] = [{'dealID': '124', 'companyName': 'Next',
                                         'expectedPriceDate': '02/03/2026'}]
        return json.dumps({'data': data})
    settings = {'_load': lambda key, ttl, loader: loader()}
    with patch.object(sources, 'read_text', side_effect=read):
        rows = sources.collect_ipos(settings, datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())
    assert {(r['name'], r['date']) for r in rows} == {
        ('Recent', '2025-12-30'), ('Example', '2026-01-20'), ('Next', '2026-02-03')}
    assert len(rows) == 3
    assert all(r['source_months'] for r in rows)


def test_calendar_estimate_range_is_one_event_with_source():
    rows = sources.calendar_records({'Earnings Date': [date(2026, 10, 28), date(2026, 11, 2)]},
                                    'EX', 'Technology', 'USD')
    assert len(rows) == 1
    assert rows[0]['date'] == '2026-10-28'
    assert rows[0]['date_end'] == '2026-11-02'
    assert rows[0]['status'] == 'provider estimate'
    assert rows[0]['source'] == 'Yahoo Finance'
    assert rows[0].get('time') is None


def test_undated_ipo_stays_undated_instead_of_using_filing_date():
    rows = sources.normalize_ipos({'data': {'upcoming': {'rows': [{
        'companyName': 'Pending', 'filedDate': '07/10/2026',
    }]}}})
    assert rows[0]['date'] is None


def test_feed_dates_are_utc_for_chronological_sorting():
    xml = ('<rss><channel><item><title>Research</title><link>https://example.org/a</link>'
           '<pubDate>Fri, 02 Oct 2026 11:00:00 +0200</pubDate></item></channel></rss>')
    assert sources.parse_feed(xml, {'name': 'Example'})[0]['published'] == '2026-10-02T09:00:00+00:00'


def test_economy_reports_observation_frequency_separately_from_date():
    settings = {'_load': lambda key, ttl, loader: [{'date': '2026-04-01', 'value': 1.2}]}
    rows = {r['id']: r for r in sources.collect_economy(settings, 1791158400)}
    assert rows['A191RL1Q225SBEA']['frequency'] == 'quarterly'
    assert rows['A191RL1Q225SBEA']['observation_period'] == '2026 Q2'
    assert rows['CPIAUCSL']['frequency'] == 'monthly'
    assert rows['CPIAUCSL']['observation_period'] == '2026-04'
    assert rows['ICSA']['frequency'] == 'weekly'
    assert rows['DGS10']['frequency'] == 'daily'


def test_specific_earnings_date_replaces_estimate_window_and_keeps_eps_units():
    settings = load_settings(None, ['EX'])
    def load(key, ttl, loader):
        if ':info:' in key:
            return {'currency': 'GBP', 'financialCurrency': 'USD'}
        if ':calendar:' in key:
            return [{'type': 'earnings', 'date': '2026-10-28', 'date_end': '2026-11-02',
                     'status': 'provider estimate'}]
        if ':earnings:' in key:
            return [{'type': 'earnings', 'date': '2026-10-29', 'time': '16:00',
                     'timezone': 'America/New_York', 'status': 'provider estimate',
                     'estimate': 1.2, 'actual': None}]
        return []
    settings['_load'] = load
    row = sources.collect_instrument('EX', settings, 1791158400)
    assert len(row['calendar']) == 1
    event = row['calendar'][0]
    assert event['date'] == '2026-10-29'
    assert event['eps_currency'] == 'USD'
    assert event['eps_unit'] == 'USD/share'
    assert event['source'] == 'Yahoo Finance'


def test_native_tls_fallback_keeps_request_identity_and_accept_headers():
    import ssl
    import subprocess
    from urllib.error import URLError
    from unittest.mock import Mock
    opener = Mock()
    opener.open.side_effect = URLError(ssl.SSLCertVerificationError('local trust missing'))
    def run(args, **kwargs):
        accepted = ('User-Agent: MarketWatch/1.0 public research' in args and 'Accept: */*' in args)
        return subprocess.CompletedProcess(args, 0 if accepted else 22,
                                           b'<rss/>' if accepted else b'', b'')
    with patch.object(sources.sys, 'platform', 'darwin'), \
         patch.object(sources, 'build_opener', return_value=opener), \
         patch.object(sources.subprocess, 'run', side_effect=run):
        assert sources.read_text('https://www.cnbc.com/id/100003114/device/rss/rss.html') == '<rss/>'
