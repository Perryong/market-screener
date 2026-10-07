import importlib.util
import json
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location('dashboard_build', Path(__file__).parents[2] / 'dashboard/build.py')
build = importlib.util.module_from_spec(spec)


def test_combined_routes_and_unavailable_data():
    spec.loader.exec_module(build)
    html = build.render({}, None, None, '<p>Desk Tape</p>')
    assert '#/entrydesk' in html and '#/technical' in html
    assert 'Entry snapshot unavailable' in html
    assert 'Desk Tape' in html and 'Breakout' in html


def test_only_public_entry_fields_and_safe_embedding():
    spec.loader.exec_module(build)
    html = build.render({}, None, {'candidates': [{'symbol': '</script><script>bad</script>', 'private': 'SECRET'}], 'private': 'SECRET'}, '')
    assert 'SECRET' not in html
    block = re.search(r'<script id="entry-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(block)['candidates'][0]['symbol'].startswith('</script>')
    assert '<script>bad</script>' not in html


def test_technical_snapshot_is_safe_and_rebuild_is_idempotent(tmp_path):
    spec.loader.exec_module(build)
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'technical.html').write_text('<script>const S = window.__DATA__ || fetch("data.json");</script>')
    payload = {'name': '</script><script>bad</script>'}
    (docs / 'data.json').write_text(json.dumps(payload))
    build.main(tmp_path)
    first = (docs / 'technical.html').read_text()
    build.main(tmp_path)
    assert (docs / 'technical.html').read_text() == first
    assert first.count('id="technical-data"') == 1
    assert '<script>bad</script>' not in first
    assert 'JSON.parse(document.getElementById' in first


def test_legacy_nonfinite_metrics_do_not_break_public_build(tmp_path):
    spec.loader.exec_module(build)
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'technical.html').write_text('<script>const S = window.__DATA__ || {};</script>')
    (docs / 'data.json').write_text('{"ranking":[{"profit_factor":Infinity,"return":2.5}],"bad":[NaN,-Infinity,1e999]}')
    build.main(tmp_path)
    payload = json.loads((docs / 'data.json').read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    assert payload == {'ranking': [{'profit_factor': None, 'return': 2.5}], 'bad': [None, None, None]}
    assert (docs / 'index.html').exists()
    first = (docs / 'technical.html').read_text()
    build.main(tmp_path)
    assert (docs / 'technical.html').read_text() == first


def test_technical_is_isolated_and_tooltip_uses_text():
    spec.loader.exec_module(build)
    html = build.render({}, None, None, '<p>Desk Tape</p>')
    assert 'sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"' in html
    assert 'allow-same-origin' not in html
    technical = (Path(__file__).parents[2] / 'docs/technical.html').read_text()
    assert 'tip.innerHTML' not in technical
    assert 'text.textContent = line' in technical


def test_strategy_route_and_public_journal_are_safely_embedded():
    spec.loader.exec_module(build)
    entries={'strategy_id':'trend-breakout-v2','journal':{'mode':'forward_shadow','observations':1,'private':'SECRET',
        'recent':[{'symbol':'BTC-USD','observed_at':1,'input_hash':'abc','private':'SECRET',
                   'outcome':{'origin':'forward_shadow','net_r':2,'private':'SECRET'}}]},'candidates':[]}
    html=build.render({},None,entries,'')
    assert '#/strategy' in html and 'Strategy overview' in html
    block=re.search(r'<script id="entry-data" type="application/json">(.*?)</script>',html,re.S).group(1)
    public=json.loads(block)
    assert public['strategy_id']=='trend-breakout-v2'
    assert public['journal']['recent'][0]['outcome']['net_r']==2
    assert 'SECRET' not in html


def test_usd_runtime_safe_idempotent_and_original_inputs_unchanged():
    from copy import deepcopy
    from screener.research_view import with_usd_display
    source={'instruments':[{'symbol':'EURUSD=X','price':1.2,'as_of':'2026-10-02','source':'</script><script>bad</script>'}]}
    original=deepcopy(source)
    first=with_usd_display('<html><head></head><body></body></html>',source)
    assert first==with_usd_display(first,source)
    assert source==original
    assert first.count('id="usd-display-runtime"')==1
    assert '<script>bad</script>' not in first


def test_breakout_marks_source_prices_without_changing_trade_inputs():
    from screener.view import level
    row={'market':'crypto','plan_entry':100,'score':75}
    html=level(row,'entry')
    assert 'data-usd-value="100"' in html
    assert 'data-usd-currency="USDT"' in html
    assert 'planned' in html
    assert row=={'market':'crypto','plan_entry':100,'score':75}


def test_entry_desk_publishes_gold_label_and_timeframe_phases():
    spec.loader.exec_module(build)
    phases = {'h4': {'phase': 'RANGE', 'position': 'INSIDE'}, 'h1': {'phase': 'NO_SETUP', 'passed': 1, 'total': 4},
              'm15': {'phase': 'WAIT'}}
    html = build.render({}, None, {'candidates': [{'symbol': 'GC=F', 'label': 'XAUUSD (GC=F proxy)', 'phases': phases}]}, '')
    block = re.search(r'<script id="entry-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    row = json.loads(block)['candidates'][0]
    assert row['label'] == 'XAUUSD (GC=F proxy)' and row['phases'] == phases
    assert '15m · 1h · 4h' in html
