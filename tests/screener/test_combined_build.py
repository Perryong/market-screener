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


def test_technical_is_isolated_and_tooltip_uses_text():
    spec.loader.exec_module(build)
    html = build.render({}, None, None, '<p>Desk Tape</p>')
    assert 'sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"' in html
    assert 'allow-same-origin' not in html
    technical = (Path(__file__).parents[2] / 'docs/technical.html').read_text()
    assert 'tip.innerHTML' not in technical
    assert 'text.textContent = line' in technical
