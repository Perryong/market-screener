/* Display-only currency conversion. Never used by strategy engines or saved positions. */
const USDDisplay=(()=>{
  const finite=x=>typeof x==='number'&&Number.isFinite(x);
  const dayMs=86400000;
  function create(snapshot={},now=Date.now()/1000){
    const rates={USD:{rate:1,date:null,source:'US dollar'}}, pairs=new Map();
    const today=new Date(now*1000).toISOString().slice(0,10);
    const validDate=date=>typeof date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(date)&&
      Number.isFinite(Date.parse(date+'T00:00:00Z'))&&new Date(date+'T00:00:00Z').toISOString().slice(0,10)===date&&date<=today&&
      now*1000-Date.parse(date+'T00:00:00Z')<=7*dayMs;
    for(const record of snapshot.instruments||[]){
      if(!/^[A-Z]{6}=X$/.test(record.symbol))continue;
      const failed=(snapshot.resources||[]).some(r=>['Yahoo:'+record.symbol,'Yahoo:history:'+record.symbol].includes(r.id)&&r.status!=='ok');
      if(failed)continue;
      const values=new Map((record.history||[]).filter(p=>validDate(p.date)&&finite(p.close)&&p.close>0).map(p=>[p.date,p.close]));
      if(validDate(record.as_of)&&finite(record.price)&&record.price>0)values.set(record.as_of,record.price);
      pairs.set(record.symbol.slice(0,6),{values,source:record.source||'Published FX snapshot'});
    }
    const latest=values=>[...values.keys()].sort().at(-1);
    // Direct quotes first. An explicitly quoted USDT rate is handled separately below.
    for(const [pair,{values,source}] of pairs){
      const date=latest(values);if(!date)continue;
      if(pair.endsWith('USD'))rates[pair.slice(0,3)]={rate:values.get(date),date,source:source+' · '+pair};
      else if(pair.startsWith('USD'))rates[pair.slice(3)]={rate:1/values.get(date),date,source:source+' · inverse '+pair};
    }
    const eur=pairs.get('EURUSD');
    if(eur)for(const [pair,{values,source}] of pairs){
      const currency=pair.slice(3);
      if(!pair.startsWith('EUR')||currency==='USD'||rates[currency])continue;
      const date=[...values.keys()].filter(d=>eur.values.has(d)).sort().at(-1);
      if(date)rates[currency]={rate:eur.values.get(date)/values.get(date),date,source:source+' · EURUSD / '+pair+' (same date)'};
    }
    const tether=(snapshot.api_data?.crypto||[]).find(r=>r.id==='tether'&&r.currency==='USD');
    const observed=Date.parse(tether?.observed_at||'')/1000;
    if(!(snapshot.resources||[]).some(r=>r.id==='CoinGecko:markets'&&r.status!=='ok')&&finite(tether?.price)&&tether.price>0&&finite(observed)&&observed<=now&&now-observed<=86400){
      rates.USDT={rate:tether.price,date:tether.observed_at,source:tether.source||'CoinGecko'};
    }
    function convert(value,currency){
      if(!finite(value))return null;
      const pence=currency==='GBp'||currency==='GBX';
      const rate=rates[pence?'GBP':currency]?.rate;
      if(!finite(rate)||rate<=0)return null;
      const converted=value*rate/(pence?100:1);
      return finite(converted)?converted:null;
    }
    return {rates,convert};
  }
  function format(value,compact=false){
    if(!finite(value))return 'USD unavailable';
    const abs=Math.abs(value);
    if(compact&&abs>=1e6){const [scale,suffix]=abs>=1e12?[1e12,'T']:abs>=1e9?[1e9,'B']:[1e6,'M'];return '$'+new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value/scale)+suffix;}
    const digits=abs>0&&abs<1?Math.max(4,3-Math.floor(Math.log10(abs))):2;
    if(digits>20)return '$'+value.toPrecision(4);
    return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:abs>0&&abs<1?0:2,maximumFractionDigits:digits}).format(value);
  }
  function monetaryUnit(unit){
    const match=/^(USD|EUR|GBP|CHF|DKK|SEK|NOK|JPY|CAD|AUD|NZD|HKD|SGD|CNY|INR|ZAR|BRL|MXN|KRW)(?:\/(share|shares|xbrli:shares))?$/.exec(unit||'');
    return match?{currency:match[1],perShare:!!match[2]}:null;
  }
  return {create,format,monetaryUnit};
})();
if(typeof module!=='undefined')module.exports=USDDisplay;
