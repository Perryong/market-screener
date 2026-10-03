"""Immutable first observations and subsequent, explicitly simulated shadow outcomes."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .data import finite, validate_bars, validate_interval
from .validation import COSTS, STRATEGY_ID, confirmation, metrics, simulate_trade


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


class Journal:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, observed REAL NOT NULL, symbol TEXT NOT NULL, source TEXT NOT NULL, asset TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS outcomes (id TEXT PRIMARY KEY REFERENCES observations(id), payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS paths (id TEXT NOT NULL, start REAL NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (id,start))')
        self.db.commit()

    def close(self):
        self.db.close()

    def observe(self,bundle,candidate,observed_at):
        if not finite(observed_at) or observed_at<0:
            raise ValueError('finite observation time required')
        symbol,source,asset=(bundle.get(k) for k in ('symbol','source','asset_class'))
        if not isinstance(symbol,str) or not symbol or not isinstance(source,str) or not source or asset not in COSTS:
            raise ValueError('journal requires source, instrument and asset identity')
        if candidate.get('strategy_id')!=STRATEGY_ID or candidate.get('symbol')!=symbol or candidate.get('source')!=source or candidate.get('asset_class')!=asset:
            raise ValueError('candidate identity or strategy mismatch')
        bars=bundle.get('bars_1h',[]);quarters=bundle.get('bars_15m',[])
        validate_bars(bars,observed_at);validate_interval(bars,3600)
        validate_bars(quarters,observed_at);validate_interval(quarters,900)
        signal_time=bars[-1]['end'] if bars else int(observed_at//3600)*3600
        identifier=hashlib.sha256(encoded([symbol,asset,source,STRATEGY_ID,signal_time]).encode()).hexdigest()
        reference=candidate.get('reference_levels') or {}
        eligible=bool(bars and candidate.get('side')=='LONG' and asset in ('stocks','crypto')
            and (asset=='crypto' or bundle.get('market_open') is True)
            and not bundle.get('stale') and 0<=observed_at-signal_time<=75*60
            and confirmation(bars,quarters,'LONG')
            and not any(not e.startswith('quote:') for e in bundle.get('errors',[]))
            and all(finite(reference.get(k)) and reference[k]>0 for k in ('entry','stop','target'))
            and reference.get('stop',0)<reference.get('entry',0)<reference.get('target',0))
        inputs={k:bundle.get(k) for k in ('symbol','asset_class','source','contract_kind','currency','bars_1h','bars_15m','quote','market_open','stale','errors')}
        row=dict(id=identifier,strategy_id=STRATEGY_ID,symbol=symbol,asset_class=asset,source=source,
            observed_at=observed_at,signal_time=signal_time,input_hash=hashlib.sha256(encoded(inputs).encode()).hexdigest(),
            state=candidate.get('state'),side=candidate.get('side'),score=candidate.get('score'),
            reasons=candidate.get('reasons',[]),reference_levels=reference,factors=candidate.get('factors',{}),
            cost_per_side=COSTS[asset],shadow_eligible=eligible,
            shadow_note='Completed-candle hypothetical fills only; quote execution remains unvalidated',
            risk=reference['entry']-reference['stop'] if eligible else None)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                (identifier,observed_at,symbol,source,asset,encoded(row)))
        return json.loads(self.db.execute('SELECT payload FROM observations WHERE id=?',(identifier,)).fetchone()[0])

    def resolve(self,bundle,observed_at):
        bars=bundle.get('bars_1h',[])
        validate_bars(bars,observed_at);validate_interval(bars,3600)
        if bundle.get('stale') or not bars:
            return
        records=self.db.execute('SELECT o.id,o.payload FROM observations o LEFT JOIN outcomes r ON o.id=r.id WHERE r.id IS NULL AND o.symbol=? AND o.source=? AND o.asset=?',
            (bundle.get('symbol'),bundle.get('source'),bundle.get('asset_class'))).fetchall()
        for identifier,raw in records:
            row=json.loads(raw)
            if not row['shadow_eligible'] or row['strategy_id']!=STRATEGY_ID or observed_at<=row['observed_at']:
                continue
            future=[b for b in bars if b['start']>row['observed_at']]
            if not future:
                if observed_at>row['observed_at']+2*3600+3600:
                    self._outcome(identifier,dict(status='expired',reason='No completed entry bar within two hours',closed=False),observed_at)
                continue
            if future[0]['start']>row['observed_at']+2*3600:
                self._outcome(identifier,dict(status='expired',reason='Entry window elapsed',closed=False),observed_at);continue
            # Require the complete path from the recorded signal through the entry bar.
            path=[b for b in bars if b['end']>=row['signal_time'] and b['start']<=future[0]['start']]
            try:
                from .validation import contiguous
                if not path or path[0]['end']!=row['signal_time'] or not all(contiguous(a,b,row['asset_class']) for a,b in zip(path,path[1:])):
                    raise ValueError('Missing bars between observation and entry')
                with self.db:
                    self.db.executemany('INSERT OR IGNORE INTO paths VALUES (?,?,?)',[(identifier,b['start'],encoded(b)) for b in future[:24]])
                frozen=[json.loads(item[0]) for item in self.db.execute('SELECT payload FROM paths WHERE id=? ORDER BY start LIMIT 24',(identifier,))]
                trade=simulate_trade(frozen,0,row['side'],row['risk'],row['asset_class'],cost_per_side=row['cost_per_side'])
                if trade is not None:
                    trade.pop('exit_index',None)
                    self._outcome(identifier,dict(trade,status='closed',closed=True),observed_at)
            except ValueError as exc:
                self._outcome(identifier,dict(status='unavailable',reason=str(exc),closed=False),observed_at)

    def _outcome(self,identifier,outcome,observed_at):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?)',
                (identifier,encoded(dict(outcome,origin='forward_shadow',resolved_at=observed_at))))

    def summary(self):
        rows=[];closed=[];eligible=0;unresolved=0
        for raw,outcome in self.db.execute('SELECT o.payload,r.payload FROM observations o LEFT JOIN outcomes r ON o.id=r.id ORDER BY o.observed DESC,o.id'):
            row=json.loads(raw);row['outcome']=json.loads(outcome) if outcome else None
            eligible+=bool(row['shadow_eligible']);unresolved+=bool(row['shadow_eligible'] and not outcome)
            if row['outcome'] and row['outcome'].get('closed'):
                closed.append(row['outcome'])
            # Factors stay in the private audit record; public rows are compact.
            row.pop('factors',None);row.pop('risk',None)
            rows.append(row)
        closed.sort(key=lambda t:t['exit_time'])
        return dict(mode='forward_shadow',strategy_id=STRATEGY_ID,observations=len(rows),eligible=eligible,
            pending=unresolved,closed_shadow=len(closed),forward_paper_closes=0,
            performance={k:v for k,v in metrics(closed).items() if k in ('trades','expectancy','profit_factor')},recent=rows[:50],
            note='Immutable first observations. Shadow fills do not satisfy genuine forward-paper readiness.')
