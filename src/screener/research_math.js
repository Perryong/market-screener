/* Pure research calculations. Decimal ratios; missing data stays missing. */
const ResearchMath = (() => {
  const numeric = x => typeof x === 'number' && Number.isFinite(x);
  function filterInstruments(records, filters = {}) {
    return records.filter(r => (!filters.kind || r.kind === filters.kind) &&
      (!filters.region || r.region === filters.region) && (!filters.sector || r.sector === filters.sector) &&
      (!filters.family || r.family === filters.family) && (!filters.category || r.category === filters.category) &&
      (!filters.query || `${r.symbol} ${r.name}`.toLowerCase().includes(filters.query.toLowerCase())) &&
      Object.entries(filters.ranges || {}).every(([key, range]) => {
        const value = r.metrics?.[key];
        return numeric(value) && (range.min == null || value >= range.min) && (range.max == null || value <= range.max);
      }));
  }
  function validateScreen(value,keys) {
    const fields=['query','region','sector','family','category','ranges','sort','ascending'];
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!fields.includes(k)))throw new Error('Invalid screen field.');
    const output={};for(const key of fields){if(!(key in value))continue;const v=value[key];if(key==='ranges'){if(!v||typeof v!=='object'||Array.isArray(v))throw new Error('Invalid ranges.');output.ranges={};for(const [metric,range] of Object.entries(v)){if(!keys.includes(metric)||!range||typeof range!=='object'||Object.keys(range).some(k=>!['min','max'].includes(k)))throw new Error('Invalid range field.');if([range.min,range.max].some(x=>x!=null&&!numeric(x)))throw new Error('Range must contain finite numbers.');output.ranges[metric]={min:range.min??null,max:range.max??null};}}else if(key==='ascending'){if(typeof v!=='boolean')throw new Error('Invalid sort direction.');output[key]=v;}else{if(typeof v!=='string'||v.length>500||key==='sort'&&!keys.includes(v))throw new Error('Invalid screen field.');output[key]=v;}}
    return output;
  }
  function compareHistory(records, benchmark) {
    const all = benchmark && !records.some(r => r.symbol === benchmark.symbol) ? [...records, benchmark] : records;
    const maps = all.map(r => new Map((r.history || []).filter(p => numeric(p.close) && p.close > 0).map(p => [p.date,p.close])));
    const dates = maps.length ? [...maps[0].keys()].filter(d => maps.every(m => m.has(d))).sort() : [];
    return {dates, series: all.map((r,i) => ({symbol:r.symbol, currency:r.currency, values:dates.map(d => 10000*maps[i].get(d)/maps[i].get(dates[0]))}))};
  }
  function fundOverlap(a,b) {
    const weights = new Map((b.holdings || []).map(h => [h.symbol,h.weight]));
    return (a.holdings || []).reduce((sum,h) => sum+Math.min(h.weight,weights.get(h.symbol) || 0),0);
  }
  function presetLists(records) {
    const stocks = records.filter(r => r.kind === 'stock');
    const qualifies = (r,key,min) => numeric(r.metrics?.[key]) && r.metrics[key] >= min;
    return {
      growers:stocks.filter(r=>qualifies(r,'revenue_growth',.15)&&qualifies(r,'net_margin',.10)&&qualifies(r,'revenue',5e8)),
      cash:stocks.filter(r=>qualifies(r,'fcf_margin',.25)&&qualifies(r,'revenue',1e9)),
      fortress:stocks.filter(r=>numeric(r.metrics?.cash)&&numeric(r.metrics?.debt)&&r.metrics.cash>r.metrics.debt&&qualifies(r,'current_ratio',2)&&qualifies(r,'revenue',5e8)),
      dividends:stocks.filter(r=>qualifies(r,'dividend_yield',.000001)).sort((a,b)=>b.metrics.dividend_yield-a.metrics.dividend_yield),
      capital:stocks.filter(r=>qualifies(r,'roe',.25)&&qualifies(r,'revenue',1e9)),
      largest:[...stocks].filter(r=>numeric(r.metrics?.market_cap)&&r.metrics.market_cap>0&&r.currency&&r.currency!=='Unknown').sort((a,b)=>(a.sector||'Unknown').localeCompare(b.sector||'Unknown')||a.currency.localeCompare(b.currency)||b.metrics.market_cap-a.metrics.market_cap),
    };
  }
  function validatePortfolio(value) {
    if(!Array.isArray(value)||value.length>500)throw new Error('Portfolio must be an array of up to 500 positions.');
    const allowed=['symbol','quantity','purchase_price','purchase_date'];
    return value.map(row=>{
      if(!row||typeof row!=='object'||Object.keys(row).some(k=>!allowed.includes(k)))throw new Error('Unexpected portfolio field.');
      if(typeof row.symbol!=='string'||! /^[A-Z^][A-Z0-9.^=-]{0,24}$/.test(row.symbol))throw new Error('Invalid ticker.');
      if(!numeric(row.quantity)||row.quantity<=0||row.quantity>1e15)throw new Error('Quantity must be a finite positive number.');
      if(row.purchase_price!=null&&(!numeric(row.purchase_price)||row.purchase_price<0||row.purchase_price>1e15))throw new Error('Purchase price must be a finite nonnegative number.');
      if(row.purchase_date!=null){const parsed=new Date(row.purchase_date+'T00:00:00Z');if(typeof row.purchase_date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(row.purchase_date)||!Number.isFinite(parsed.getTime())||parsed.toISOString().slice(0,10)!==row.purchase_date)throw new Error('Invalid purchase date.');}
      return {symbol:row.symbol,quantity:row.quantity,purchase_price:row.purchase_price??null,purchase_date:row.purchase_date??null};
    });
  }
  function portfolioExposure(positions,instruments) {
    positions=validatePortfolio(positions);
    const records=new Map(instruments.map(r=>[r.symbol,r])),currencies=Object.create(null),underlying=new Map(),missing=[];
    for(const p of positions){const r=records.get(p.symbol);if(!r||!numeric(r.price)||r.price<=0||!r.currency||r.currency==='Unknown'){missing.push(p.symbol);continue;}
      const total=p.quantity*r.price,currency=r.currency;if(!currencies[currency])currencies[currency]={value:0,cost:0,costed_value:0,unknown:0};const bucket=currencies[currency];bucket.value+=total;if(p.purchase_price!=null){bucket.cost+=p.quantity*p.purchase_price;bucket.costed_value+=total;}
      const add=(symbol,value)=>{const key=currency+':'+symbol,record=records.get(symbol);if(!underlying.has(key))underlying.set(key,{symbol,currency,value:0,sector:record?.sector||'Unknown',country:record?.country||'Unknown',positions:[]});const row=underlying.get(key);row.value+=value;row.positions.push(p.symbol);};
      if(r.kind==='fund'){const rows=(r.holdings||[]).filter(h=>typeof h.symbol==='string'&&numeric(h.weight)&&h.weight>0&&h.weight<=1);const sum=rows.reduce((s,h)=>s+h.weight,0);if(sum>1.001){bucket.unknown+=total;continue;}for(const h of rows)add(h.symbol,total*h.weight);bucket.unknown+=total*Math.max(0,1-sum);}
      else add(r.symbol,total);
    }
    return {currencies,underlying:[...underlying.values()].sort((a,b)=>a.currency.localeCompare(b.currency)||b.value-a.value),missing};
  }
  function marketSummary(records,region,period='day') {
    const all=records.filter(r=>r.kind==='stock'&&r.region===region),sectors=new Map(),countries=new Map();
    const dates=all.map(r=>r.as_of).filter(Boolean),counts=new Map();dates.forEach(d=>counts.set(d,(counts.get(d)||0)+1));const asOf=[...counts].sort((a,b)=>b[1]-a[1]||b[0].localeCompare(a[0]))[0]?.[0]||null;
    const rows=all.filter(r=>(!asOf||r.as_of===asOf)&&numeric(r.metrics?.[period]));
    for(const r of rows){const cap=r.metrics?.market_cap;if(!numeric(cap)||cap<=0||!r.currency||r.currency==='Unknown')continue;for(const [key,map] of [['sector',sectors],['country',countries]]){const name=r[key]||'Unknown',id=r.currency+':'+name;if(!map.has(id))map.set(id,{name,currency:r.currency,cap:0,weighted:0,count:0});const entry=map.get(id);entry.cap+=cap;entry.weighted+=cap*r.metrics[period];entry.count++;}}
    const summarize=map=>[...map.values()].map(r=>({...r,return:r.weighted/r.cap})).sort((a,b)=>b.return-a.return);
    const known=key=>rows.filter(r=>r.metrics?.[key]!=null);
    return {asOf,rows,sectors:summarize(sectors),countries:summarize(countries),breadth:{covered:all.length,count:rows.length,up:rows.filter(r=>r.metrics[period]>0).length,down:rows.filter(r=>r.metrics[period]<0).length,highs:known('new_high').filter(r=>r.metrics.new_high).length,lows:known('new_low').filter(r=>r.metrics.new_low).length,above50:known('above50').length?known('above50').filter(r=>r.metrics.above50).length/known('above50').length:null,above200:known('above200').length?known('above200').filter(r=>r.metrics.above200).length/known('above200').length:null}};
  }
  function calendarRows(records,type,window,today) {
    const current=new Date(today+'T00:00:00Z'),day=86400000,monday=current.getTime()-((current.getUTCDay()+6)%7)*day;
    let start=current.getTime(),end=start+7*day;
    if(window==='week'){start=monday;end=start+7*day;}else if(window==='next'){start=monday+7*day;end=start+7*day;}else if(window==='later'){start=monday+14*day;end=start+90*day;}else if(window==='upcoming'){end=start+90*day;}else if(window==='month'){end=start+30*day;}else if(window==='past'){end=start;start-=30*day;}
    const valid=d=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(d)&&Number.isFinite(Date.parse(d+'T00:00:00Z'))&&new Date(d+'T00:00:00Z').toISOString().slice(0,10)===d;
    return records.filter(r=>r.type===type&&valid(r.date)&&Date.parse((valid(r.date_end)&&r.date_end>=r.date?r.date_end:r.date)+'T00:00:00Z')>=start&&Date.parse(r.date+'T00:00:00Z')<end).sort((a,b)=>a.date.localeCompare(b.date)||String(a.symbol||'').localeCompare(String(b.symbol||'')));
  }
  function resourceStatus(resource,now=Date.now()/1000) {
    if(!resource)return 'unverified';
    if(resource.status!=='ok')return resource.status||'unverified';
    if(resource.error)return 'stale';
    if(!numeric(resource.fetched_at)||resource.fetched_at<=0||resource.fetched_at>now||!numeric(resource.max_age_seconds)||resource.max_age_seconds<=0)return 'unverified';
    return now-resource.fetched_at>=resource.max_age_seconds?'stale':'ok';
  }
  function newsRows(records,filters={}) {
    return records.filter(r=>(!filters.category||r.category===filters.category)&&(!filters.ticker||(r.tickers||[]).includes(filters.ticker))&&(!filters.longform||r.longform)&&(!filters.query||`${r.title} ${r.excerpt||''} ${r.publisher}`.toLowerCase().includes(filters.query.toLowerCase()))).sort((a,b)=>(Date.parse(b.published)||0)-(Date.parse(a.published)||0));
  }
  return {numeric,filterInstruments,validateScreen,compareHistory,fundOverlap,presetLists,validatePortfolio,portfolioExposure,marketSummary,calendarRows,newsRows,resourceStatus};
})();
if (typeof module !== 'undefined') module.exports = ResearchMath;
