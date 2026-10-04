"""Build the read-only combined desk from public snapshots only."""
import json
from html import escape
from pathlib import Path
from screener.research_view import render_app, with_usd_display
from screener.research_sources import financial_unit
from screener.shared import atomic_text

ENTRY_FIELDS = ('strategy_id','signal_time','symbol','asset_class','source','as_of','state','side','entry','stop','target','net_rr','score','factors','setup_evidence','reasons','validation','reference_levels')


def embedded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def render(strategy, research, entries, technical):
    strategy = {'version': 1, 'mode': 'live', 'generated_at': 0, 'results': [], 'trades': [], **strategy}
    public = {key: entries[key] for key in ('version','strategy_id','generated_at','validation','status','errors') if entries and key in entries}
    journal=(entries or {}).get('journal') or {}
    public['journal']={k:journal[k] for k in ('mode','strategy_id','observations','eligible','pending','closed_shadow','forward_paper_closes','note') if k in journal}
    public['journal']['performance']={k:v for k,v in journal.get('performance',{}).items() if k in ('trades','expectancy','profit_factor')}
    recent=[]
    for row in journal.get('recent',[])[:50]:
        safe={k:row[k] for k in ('id','strategy_id','symbol','asset_class','source','observed_at','signal_time','input_hash','state','side','score','reasons','reference_levels','cost_per_side','shadow_eligible','shadow_note') if k in row}
        safe['outcome']={k:v for k,v in (row.get('outcome') or {}).items() if k in ('origin','status','closed','entry_time','exit_time','entry','exit','stop','target','side','exit_reason','net_r','net_return','net_risk','resolved_at','reason')} or None
        recent.append(safe)
    public['journal']['recent']=recent
    public['candidates'] = [{key: row[key] for key in ENTRY_FIELDS if key in row} for row in (entries or {}).get('candidates', [])]
    html = render_app(strategy, research)
    notice = '' if entries else '<div class="banner">Entry snapshot unavailable. Collect public entry evidence to populate this desk.</div>'
    return html.replace('<main id="content"', notice + '<main id="content"').replace('<section id="breakout-panel"', '<section id="technical-panel" hidden><iframe title="Desk Tape technical analysis" id="technical-frame" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" srcdoc="'+escape(technical, quote=True)+'" style="width:100%;height:85vh;border:0"></iframe></section><section id="breakout-panel"').replace('<script id="research-data"', '<script id="entry-data" type="application/json">'+embedded(public)+'</script><script id="research-data"')


def load(path):
    return json.loads(path.read_text()) if path.exists() else None


def main(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    docs = root/'docs'
    # Compact public snapshots without changing any values or historical coverage.
    for name in ('data.json', 'latest.json', 'research.json', 'entries.json'):
        path = docs/name
        if path.exists():
            atomic_text(path, json.dumps(load(path), ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n')
    research=load(docs/'research.json')
    if research:
        for record in research.get('instruments',[]):
            for row in record.get('financials',[]):
                if str(row.get('source','')).startswith('Yahoo'):
                    row['unit']=financial_unit(row.get('metric'),record.get('financial_currency') or record.get('currency','Unknown'))
        atomic_text(docs/'research.json',json.dumps(research,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    technical = (docs/'technical.html').read_text()
    # Replace the previous embedded public snapshot, preserving the original application.
    import re
    technical = re.sub(r'<script id="technical-data".*?</script>', '', technical, flags=re.S)
    technical = technical.replace('window.__DATA__ ||', "JSON.parse(document.getElementById('technical-data').textContent) ||")
    technical = '<script id="technical-data" type="application/json">'+embedded(load(docs/'data.json'))+'</script>'+technical
    technical=with_usd_display(technical,research)
    atomic_text(docs/'technical.html', technical)
    atomic_text(docs/'index.html', render(load(docs/'latest.json') or {}, load(docs/'research.json'), load(docs/'entries.json'), technical))


if __name__ == '__main__':
    main()
