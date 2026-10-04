const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('docs/technical.html', 'utf8');
const source = html.slice(html.indexOf('const $ ='), html.indexOf('/* interaction:'));
function dashboard(rate = 0.98, converterAvailable = true) {
  const nodes = {};
  const document = {querySelector: s => nodes[s] ||= {}, documentElement: {style: {setProperty() {}}}};
  const window = {__USD_DISPLAY__: {convert: (value, currency) =>
    typeof value !== 'number' || !Number.isFinite(value) ? null : currency === 'USD' ? value : rate == null ? null : value * rate}};
  if (!converterAvailable) delete window.__USD_DISPLAY__;
  const USDDisplay = {format: value => value == null ? 'USD unavailable' : '$' + value.toFixed(2)};
  return {...new Function('document', 'window', 'USDDisplay', source + '\nreturn {rows,renderTape,renderChart,renderInstruments,renderPanels,pivotChart,tvSymbolFor};')(document, window, USDDisplay), nodes};
}
function fixture(quote = {}) {
  return {symbols: {NVDA: {label: 'Nvidia', group: 'Semis', sections: {
    analysis: {ok: true, stale: true, as_of: '2026-09-20T00:00:00Z', data: {price_data: {current_price: 222.27, change_percent: -0.5}, rsi: {value: 52}}},
    quote: {ok: true, as_of: '2026-10-04T00:00:00Z', data: {price: 233.95, change_percent: 1.2}, ...quote}
  }}}};
}
test('newer successful quote replaces headline without freshening stale indicators', () => {
  const app = dashboard(), snapshot = fixture(), original = JSON.stringify(snapshot);
  const row = app.rows(snapshot)[0];
  assert.equal(row.price, 233.95);
  assert.equal(row.chg, 1.2);
  assert.equal(row.rsi, 52);
  assert.equal(row.stale, true);
  assert.equal(row.secs.analysis.as_of, '2026-09-20T00:00:00Z');
  assert.equal(JSON.stringify(snapshot), original);
  app.renderInstruments(snapshot);
  assert.match(app.nodes['#instruments tbody'].innerHTML, /\$233\.95/);
  assert.match(app.nodes['#instruments tbody'].innerHTML, /stale/);
});
test('older, failed, stale or invalid quotes cannot override analysis', () => {
  const app = dashboard();
  for (const quote of [{as_of: '2026-09-19T00:00:00Z'}, {as_of: 'bad'}, {ok: false}, {stale: true}, {data: {price: NaN}}, {data: {price: -1}}, {data: {price: null}}]) {
    assert.equal(app.rows(fixture(quote))[0].price, 222.27);
  }
});
test('crypto movers read actual schema and convert USDT while USD snapshots and index/FX units stay correct', () => {
  const app = dashboard();
  app.renderPanels({market: {gainers: {ok: true, data: {coins: [{symbol: 'TESTUSDT', changePercent: 5.4, indicators: {close: 100}}]}}, snapshot: {ok: true, data: {crypto: [{symbol: 'BTC-USD', price: 100}], indices: [{symbol: '^SPX', price: 100}], fx: [{symbol: 'EURUSD=X', price: 1.05}]}}}});
  const panels = app.nodes['#panels'].innerHTML;
  assert.match(panels, /TESTUSDT<\/td><td class="num">\$98\.00<\/td>/);
  assert.match(panels, /\+5\.40%/);
  assert.match(panels, /BTC-USD<\/td>\s*<td class="num">\$100\.00/);
  assert.match(panels, /100\.00 pts/);
  assert.match(panels, /1\.05000/);
});
test('main crypto and pivot candles use quoted USD conversion without mutating report', () => {
  const app = dashboard();
  const snapshot = {symbols: {BTCUSDT: {label: 'Bitcoin', sections: {analysis: {ok: true, data: {price_data: {current_price: 100, change_percent: 2}}}}}}};
  app.renderTape(snapshot);
  assert.match(app.nodes['#tape'].innerHTML, /\$98\.00/);
  const market = {id: 'BTC', tradingview_symbol: 'BINANCE:BTCUSDT', lower: 100, upper: 110, close: 105, bullish_targets: [112], bearish_targets: [98], analysis_candles: Array.from({length: 4}, (_, i) => ({complete: true, start: 1700000000 + i * 14400, open: 102, high: 114, low: 96, close: 105}))};
  const original = JSON.stringify(market), chart = app.pivotChart(market);
  assert.match(chart, /L \$98\.00/);
  assert.match(chart, /U \$107\.80/);
  assert.match(chart, /\$102\.90/);
  assert.match(chart, /T1 \$109\.76/);
  assert.equal(JSON.stringify(market), original);
  assert.match(dashboard(null).pivotChart(market), /USD unavailable/);
});
test('missing USDT conversion fails closed while USD data remains available', () => {
  for (const app of [dashboard(null), dashboard(null, false)]) {
  app.renderTape({symbols: {BTCUSDT: {sections: {analysis: {ok: true, data: {price_data: {current_price: 100}}}}}, SPY: {sections: {analysis: {ok: true, data: {price_data: {current_price: 100}}}}}}});
  assert.match(app.nodes['#tape'].innerHTML, /USD unavailable/);
  assert.match(app.nodes['#tape'].innerHTML, /\$100\.00/);
  }
});
test('structured setup ratios show supplied target values and preserve stale analysis status', () => {
  const app = dashboard(), snapshot = fixture();
  snapshot.symbols.NVDA.sections.analysis.data.trade_setup = {risk_reward: {to_target_1: 1.6, to_target_2: 2, quality: 'Good', measured_from_entry: 218.5}};
  const original = JSON.stringify(snapshot);
  app.renderInstruments(snapshot);
  const table = app.nodes['#instruments tbody'].innerHTML;
  assert.match(table, /T1 1\.60 · T2 2\.00/);
  assert.doesNotMatch(table, /\[object Object\]/);
  assert.match(table, /stale/);
  assert.equal(JSON.stringify(snapshot), original);
});
test('legacy and incomplete setup ratios retain valid values without inventing missing targets', () => {
  const app = dashboard();
  for (const [value, expected] of [[1.6, '1.60'], [0, '0.00'], ['1:2 <test>', '1:2 &lt;test&gt;'], [null, '—'], [{quality: 'Good'}, '—'], [{to_target_1: null, to_target_2: 2}, 'T2 2.00'], [{to_target_1: Infinity}, '—']]) {
    const snapshot = fixture();
    snapshot.symbols.NVDA.sections.analysis.stale = false;
    snapshot.symbols.NVDA.sections.analysis.data.trade_setup = {risk_reward: value};
    app.renderInstruments(snapshot);
    assert.ok(app.nodes['#instruments tbody'].innerHTML.includes(`<td class="num">${expected}</td>`), `ratio ${JSON.stringify(value)} must render ${expected}`);
  }
});
test('live reference feeds map only exact BTC/ETH USDT symbols without mutating source venues', () => {
  const app = dashboard();
  for (const [venue, expected] of [['BINANCE:BTCUSDT', 'COINBASE:BTCUSD'], ['KUCOIN:ETHUSDT', 'COINBASE:ETHUSD'], ['BINANCE:BTCUSDTPERP', 'BINANCE:BTCUSDTPERP'], ['BINANCE:BNBUSDT', 'BINANCE:BNBUSDT'], ['NASDAQ:NVDA', 'NASDAQ:NVDA'], ['OANDA:XAUUSD', 'OANDA:XAUUSD']]) {
    const row = {venue, key: venue.split(':')[1], group: 'Crypto'};
    assert.equal(app.tvSymbolFor(row), expected);
    assert.equal(row.venue, venue);
  }
});
