const assert = require('node:assert/strict');
const fs = require('node:fs');
assert.ok(fs.existsSync('src/screener/research_math.js'), 'research math must exist');
const M = require('../../src/screener/research_math.js');
const rows = [{symbol:'A',name:'Alpha',kind:'stock',region:'US',metrics:{pe:null}},
              {symbol:'B',name:'Beta',kind:'stock',region:'US',metrics:{pe:12}}];
assert.deepEqual(M.filterInstruments(rows,{ranges:{pe:{max:20}}}).map(r=>r.symbol),['B']);
const history=M.compareHistory([{symbol:'A',history:[{date:'2026-01-01',close:100},{date:'2026-01-02',close:110}]},
                               {symbol:'B',history:[{date:'2026-01-02',close:200},{date:'2026-01-03',close:220}]}]);
assert.deepEqual(history.dates,['2026-01-02']);
assert.equal(history.series[0].values[0],10000);
assert.equal(M.fundOverlap({holdings:[{symbol:'A',weight:0.3}]},{holdings:[{symbol:'A',weight:0.2}]}),0.2);
assert.equal(M.presetLists([{symbol:'A',kind:'stock',metrics:{revenue_growth:0.2,net_margin:null,revenue:1e9}}]).growers.length,0);
assert.deepEqual(M.presetLists([{symbol:'SMALL',kind:'stock',sector:'Tech',currency:'USD',metrics:{market_cap:1,revenue:100}}, {symbol:'BIG',kind:'stock',sector:'Tech',currency:'USD',metrics:{market_cap:10,revenue:1}}, {symbol:'MISS',kind:'stock',metrics:{revenue:1000}}]).largest.map(r=>r.symbol),['BIG','SMALL']);
assert.equal(typeof M.validatePortfolio,'function','portfolio validation must exist');
assert.throws(()=>M.validatePortfolio([{symbol:'A',quantity:-1}]),/quantity/i);
assert.throws(()=>M.validatePortfolio(JSON.parse('[{"symbol":"A","quantity":1,"__proto__":{}}]')),/field/i);
assert.throws(()=>M.validatePortfolio([{symbol:'A',quantity:1,purchase_date:'2026-02-30'}]),/date/i);
const instrument=[{symbol:'FUND',kind:'fund',price:100,currency:'USD',holdings:[{symbol:'A',weight:0.3}]},
                  {symbol:'A',kind:'stock',price:10,currency:'USD',sector:'Technology',country:'US'},
                  {symbol:'EU',kind:'stock',price:20,currency:'EUR'},
                  {symbol:'NONE',kind:'stock',price:null,currency:'USD'}];
const exposure=M.portfolioExposure([{symbol:'FUND',quantity:1},{symbol:'A',quantity:1},{symbol:'EU',quantity:1},{symbol:'NONE',quantity:1}],instrument);
assert.equal(exposure.currencies.USD.value,110);
assert.equal(exposure.currencies.USD.unknown,70);
assert.equal(exposure.currencies.EUR.value,20);
assert.equal(exposure.underlying.find(r=>r.symbol==='A').value,40);
assert.deepEqual(exposure.missing,['NONE']);
assert.equal(typeof M.marketSummary,'function','market summaries must exist');
const market=M.marketSummary([{symbol:'A',kind:'stock',region:'US',currency:'USD',sector:'Tech',metrics:{market_cap:100,day:.10}},
 {symbol:'B',kind:'stock',region:'US',currency:'USD',sector:'Tech',metrics:{market_cap:300,day:-.10}},
 {symbol:'C',kind:'stock',region:'US',currency:'EUR',sector:'Tech',metrics:{market_cap:100,day:.20}},
 {symbol:'D',kind:'stock',region:'US',currency:'USD',sector:'Tech',metrics:{market_cap:null,day:.99}}],'US','day');
assert.equal(market.sectors.find(r=>r.currency==='USD').return,-.05);
assert.equal(market.sectors.find(r=>r.currency==='EUR').return,.20);
assert.deepEqual(M.calendarRows([{date:'2026-10-02',type:'earnings'},{date:null,type:'earnings'},{date:'2026-10-10',type:'earnings'}],'earnings','week','2026-10-02').map(r=>r.date),['2026-10-02']);
assert.deepEqual(M.newsRows([{title:'Old',published:'2026-01-01',category:'Tech'},{title:'New',published:'2026-01-02',category:'Tech'}],{category:'Tech'}).map(r=>r.title),['New','Old']);
console.log('Research, portfolio, market and news checks passed');
assert.equal(typeof M.validateScreen,'function','shared screens must validate untrusted filters');
assert.throws(()=>M.validateScreen({ranges:null},['pe']),/range/i);
assert.throws(()=>M.validateScreen({ranges:{pe:{max:'20'}}},['pe']),/number/i);
assert.throws(()=>M.validateScreen(JSON.parse('{"__proto__":{}}'),['pe']),/field/i);
assert.deepEqual(M.validateScreen({query:'A',ranges:{pe:{min:null,max:20}}},['pe']),{query:'A',ranges:{pe:{min:null,max:20}}});
