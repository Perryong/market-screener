"""Embed the application and data; works over HTTP and directly from disk."""
import json
from html import escape
from pathlib import Path

from .view import render as render_breakout
from .research import empty_snapshot


NAV = [('Research',[('screener','Stock screener'),('compare','Compare stocks'),('funds','Funds & ETFs'),
                    ('fund-compare','Compare funds'),('families','Fund families'),('lists','Research lists'),('portfolio','Portfolio X-Ray')]),
       ('Markets',[('markets','Today’s market'),('earnings','Earnings calendar'),('dividends','Dividend calendar'),
                   ('ipos','IPO calendar'),('economy','Economy'),('europe','European markets')]),
       ('News',[('news','Latest news'),('reads','Longer reads')]),
       ('Strategy',[('entrydesk','Entry desk'),('technical','Desk Tape technicals'),('breakout','Breakout screener'),('crypto','Crypto markets')])]


def render_app(payload, snapshot):
    missing=not snapshot
    snapshot=snapshot or empty_snapshot(payload['mode'],payload['generated_at'])
    base=Path(__file__).parent
    css=(base/'research.css').read_text()
    js=(base/'research_math.js').read_text()+'\n'+(base/'research.js').read_text()
    data=json.dumps(snapshot,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    strategy=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<','\\u003c').replace('&','\\u0026')
    navigation=''.join('<div class="nav-group"><p>'+name+'</p>'+''.join(
        f'<a href="#/{route}" data-route="{route}">{escape(label)}</a>' for route,label in links)+'</div>' for name,links in NAV)
    breakout=escape(render_breakout(payload),quote=True)
    notice='<div class="banner">No research snapshot. Run <code>python -m screener research</code> to collect free-source data.</div>' if missing else ''
    if snapshot['mode']!='live':
        notice+='<div class="banner demo-banner">SYNTHETIC RESEARCH DEMO · prices, companies and stories below are examples, not market facts.</div>'
    return f'''<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Watch · Research, Markets & News</title><style>{css}</style></head><body>
<a class="skip" href="#content">Skip to content</a><aside class="sidebar"><a class="brand" href="#/home"><span class="brand-mark">M<span>↗</span></span> MARKET WATCH</a>
<p class="brand-sub">YOUR RESEARCH DESK</p><nav aria-label="Main navigation"><a class="home-link" href="#/home" data-route="home">Overview</a>{navigation}</nav>
<div class="sidebar-bottom"><span class="status-dot"></span> Free sources. Facts first.<small>Read-only research · no orders</small></div></aside>
<div class="workspace"><header class="topbar"><div class="topbar-title">Independent research <span>/</span> <b id="crumb">Overview</b></div>
<form id="global-search" role="search"><label class="sr-only" for="global-symbol">Search companies and funds</label><input id="global-symbol" list="symbol-options" placeholder="Search ticker or company…" autocomplete="off"><datalist id="symbol-options"></datalist><button aria-label="Open searched instrument">↗</button></form>
<button id="theme" aria-label="Switch color theme">☼</button></header>{notice}<main id="content" tabindex="-1"></main>
<section id="breakout-panel" hidden><iframe title="Original breakout screener, evidence and paper journal" id="breakout-frame" srcdoc="{breakout}"></iframe></section>
<footer class="app-footer"><span>Market Watch / Research desk</span><span>Free-source snapshots · verify original filings and timestamps</span><a href="#/coverage">Data coverage ↗</a></footer></div>
<script id="research-data" type="application/json">{data}</script><script id="strategy-data" type="application/json">{strategy}</script><script>{js}</script></body></html>'''
