"""Fixed chronological research simulation; no orders or inferred paper evidence."""
import math
import statistics
import time
import random
from bisect import bisect_right
from datetime import datetime, timezone

STRATEGY_ID = 'trend-breakout-v2'

COSTS = {'stocks': .0005, 'crypto': .0015, 'commodities': .001}


def pattern(bars, factors=None):
    if len(bars) < 60:
        return None
    prior, last = bars[-21:-1], bars[-1]
    median = statistics.median(b['volume'] for b in prior)
    if median <= 0 or last['volume'] < 1.5 * median:
        return None
    side = 'LONG' if last['close'] > max(b['high'] for b in prior) else 'SHORT' if last['close'] < min(b['low'] for b in prior) else None
    if side is None or factors is None:
        return side
    if not isinstance(factors,dict) or not isinstance(factors.get('trend_momentum'),dict):
        return None
    tm=factors['trend_momentum']
    adx,rsi,hist=(tm.get(k) for k in ('adx_1h','rsi_1h','macd_hist'))
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (adx,rsi,hist)):
        return None
    if not 22<=adx<=100 or not 0<=rsi<=100:
        return None
    return side if (side=='LONG' and hist>0 and rsi>=50) or (side=='SHORT' and hist<0 and rsi<=50) else None


def confirmation(bars, bars_15m, side):
    if len(bars)<21 or side not in ('LONG','SHORT'):
        return False
    eligible=[b for b in bars_15m if b['end']<=bars[-1]['end']]
    if not eligible or eligible[-1]['end']!=bars[-1]['end']:
        return False
    level=max(b['high'] for b in bars[-21:-1]) if side=='LONG' else min(b['low'] for b in bars[-21:-1])
    return eligible[-1]['close']>level if side=='LONG' else eligible[-1]['close']<level


def grouped_expectancy(trades):
    """Moving blocks of five observed UTC exit days; uncertainty, not win odds."""
    groups={}
    for trade in trades:
        date=datetime.fromtimestamp(trade['exit_time'],timezone.utc).date().isoformat()
        groups.setdefault(date,[]).append(trade['net_r'])
    days=[groups[key] for key in sorted(groups)]
    result=dict(interval=None,days=len(days),trades=len(trades),block_days=5,replicates=1000,
                method='95% moving-block bootstrap of net R; five observed UTC exit days',
                reason='At least 30 trades and 10 distinct exit days required')
    if len(trades)<30 or len(days)<10:
        return result
    rng=random.Random(0); means=[]
    for _ in range(1000):
        sample=[]
        while len(sample)<len(days):
            start=rng.randrange(len(days)-4)
            sample.extend(days[start:start+5])
        values=[v for group in sample[:len(days)] for v in group]
        means.append(statistics.mean(values))
    means.sort()
    result.update(interval=[means[24],means[974]],reason=None)
    return result


def target_price(entry, risk, side, cost):
    """Solve net reward = 2 * net stop loss, including exit-price costs."""
    sign = 1 if side == 'LONG' else -1
    stop = entry - sign * risk
    net_risk = risk + cost * (entry + stop)
    return (sign * entry + cost * entry + (2 + 1e-10) * net_risk) / (sign - cost)


def contiguous(previous,current,asset_class):
    if current['start']==previous['end']:
        return True
    if asset_class!='stocks':
        return False
    from .data import _calendar
    calendar=_calendar(previous['end'])
    day=datetime.fromtimestamp(previous['end'],timezone.utc).date().isoformat()
    if not calendar.is_session(day) or calendar.session_close(day).timestamp()!=previous['end']:
        return False
    next_day=calendar.next_session(day)
    return current['start']==calendar.session_open(next_day).timestamp()


def simulate_trade(bars, index, side, risk, asset_class):
    from .factors import validate_quote
    if side not in ('LONG', 'SHORT') or isinstance(risk, bool) or not isinstance(risk, (int, float)) or not math.isfinite(risk) or risk <= 0:
        raise ValueError('positive finite ATR and known side required')
    sign = 1 if side == 'LONG' else -1
    entry = bars[index]['open']
    cost = COSTS[asset_class]
    stop = entry - sign * risk
    target = target_price(entry, risk, side, cost)
    valid, reason, _ = validate_quote('BUY_LONG' if sign == 1 else 'SELL_SHORT', entry, target, stop)
    if not valid:
        raise ValueError(reason)
    net_risk = risk + cost * (entry + stop)
    last_index = min(index + 23, len(bars) - 1)
    for j in range(index, last_index + 1):
        b = bars[j]
        if j>0 and not contiguous(bars[j-1],b,asset_class):
            raise ValueError('Missing bars in simulated trade path')
        if sign * (b['open'] - stop) <= 0:
            price, reason = b['open'], 'stop_gap'
        elif sign * (b['open'] - target) >= 0:
            price, reason = target, 'target'  # known open precedes ambiguous intrabar range
        elif (b['low'] <= stop if sign == 1 else b['high'] >= stop):
            price, reason = stop, 'stop'
        elif (b['high'] >= target if sign == 1 else b['low'] <= target):
            price, reason = target, 'target'
        elif j == index + 23:
            price, reason = b['close'], 'timeout'
        else:
            continue
        net = sign * (price - entry) - cost * (entry + price)
        return {'entry_time': bars[index]['start'], 'exit_time': b['end'], 'entry': entry,
                'exit': price, 'side': side, 'stop': stop, 'target': target,
                'exit_reason': reason, 'net_r': net / net_risk, 'net_risk': net_risk,
                'net_return': net / entry, 'exit_index': j}


def metrics(trades):
    equity, peak, drawdown = 1., 1., 0.
    curve = []
    for trade in trades:
        # fixed 1% equity risk; avoids confusing price returns with sizing
        equity *= max(0., 1 + .01 * trade['net_r'])
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
        curve.append({'time': trade['exit_time'], 'equity': equity})
    wins = sum(max(0., t['net_r']) for t in trades)
    losses = -sum(min(0., t['net_r']) for t in trades)
    return {'trades': len(trades), 'expectancy': statistics.mean(t['net_r'] for t in trades) if trades else None,
            'profit_factor': wins / losses if losses else None, 'max_drawdown': drawdown,
            'equity': curve, 'trade_log': trades}


def readiness(validation, now=None):
    if validation is None:
        validation = {}
    if not isinstance(validation, dict) or any(not isinstance(validation.get(k, {}), dict) for k in ('holdout', 'rule_coverage', 'forward_paper')):
        return False, ['invalid validation schema: holdout, rule_coverage and forward_paper must be objects']
    observed_now = time.time() if now is None else now
    if isinstance(observed_now, bool) or not isinstance(observed_now, (int, float)) or not math.isfinite(observed_now) or observed_now < 0:
        return False, ['finite nonnegative evaluation time required']
    holdout = (validation or {}).get('holdout', {})
    reasons = []
    if validation.get('strategy_id')!=STRATEGY_ID:
        reasons.append('validation strategy version mismatch')
    interval=holdout.get('uncertainty',{}).get('interval') if isinstance(holdout.get('uncertainty'),dict) else None
    if not isinstance(interval,list) or len(interval)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in interval) or not 0<interval[0]<=interval[1]:
        reasons.append('positive lower holdout expectancy confidence bound required')
    as_of = (validation or {}).get('as_of')
    observation_valid = (not isinstance(as_of, bool) and isinstance(as_of, (int, float))
                         and math.isfinite(as_of) and 0 <= as_of <= observed_now)
    if not observation_valid:
        reasons.append('finite validation observation time must not be in the future')
    if (validation or {}).get('rule_coverage', {}).get('confirmation_15m_replayed') is not True:
        reasons.append('completed 15-minute confirmation rule has not been historically validated')
    for key, predicate in [('trades', lambda x: x >= 30), ('expectancy', lambda x: x > 0),
                           ('profit_factor', lambda x: x > 1.1), ('max_drawdown', lambda x: 0 <= x <= .2)]:
        value = holdout.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not predicate(value):
            reasons.append('holdout ' + key + ' gate failed')
    # Forward records must explicitly identify genuine completed paper observations.
    forward = (validation or {}).get('forward_paper', {})
    records = forward.get('closed_trades', [])
    if not isinstance(records, list) or len(records) < 30 or any(
            not isinstance(t, dict) or t.get('origin') != 'forward_paper' or t.get('closed') is not True
            or any(isinstance(t.get(k), bool) or not isinstance(t.get(k), (int, float))
                   or not math.isfinite(t[k]) for k in ('entry_time', 'exit_time', 'net_r'))
            or t['exit_time'] <= t['entry_time'] for t in records):
        reasons.append('at least 30 genuine forward paper closes required')
    elif not observation_valid or any(t['entry_time'] < 0 or t['exit_time'] > as_of for t in records):
        reasons.append('forward paper events must precede validation observation time')
    elif any(current['entry_time'] < previous['exit_time'] for previous, current in zip(records, records[1:])):
        reasons.append('forward paper closes must be unique, chronological and nonoverlapping')
    return not reasons, reasons


def backtest(bars, asset_class, bars_15m=None):
    from .factors import build_factors, validate_bars
    from .data import validate_interval
    if asset_class not in COSTS:
        raise ValueError('unknown asset class')
    now=max((b.get('end',0) for b in bars),default=0)
    validate_bars(bars,now); validate_interval(bars,3600)
    confirmed=bars_15m is not None
    quarters=bars_15m or []
    # Confirmations may extend beyond the last hourly candle; prefix slicing below excludes them.
    validate_bars(quarters,max(now,max((b.get('end',0) for b in quarters),default=0)))
    validate_interval(quarters,900)
    ends=[b['end'] for b in quarters]
    eligible_indices=[i for i,b in enumerate(bars) if i>=59 and (not confirmed or (quarters and quarters[0]['start']<=b['start'] and b['end']<=quarters[-1]['end']))]
    start_index=eligible_indices[0] if eligible_indices else len(bars)
    stop_index=eligible_indices[-1]+1 if eligible_indices else len(bars)
    split=start_index+int((stop_index-start_index)*.8)
    trades=[]; i=start_index; rejected=0; missing_confirmation=0; busy={'LONG':-1,'SHORT':-1}
    while i<min(stop_index,len(bars)-1):
        if not pattern(bars[max(0,i-59):i+1]):
            i+=1; continue
        prefix=bars[:i+1]
        q_end=bisect_right(ends,bars[i]['end'])
        q=quarters[max(0,q_end-96):q_end]
        factors=build_factors(prefix,q if confirmed else [])
        side=pattern(prefix,factors)
        if side and i<busy[side]:
            i+=1; continue
        if side and confirmed and not confirmation(prefix,q,side):
            missing_confirmation+=1; i+=1; continue
        risk=build_factors(prefix[:-1],[])['volatility_channel'].get('atr_1h') if side else None
        if side and isinstance(risk,(int,float)) and math.isfinite(risk) and risk>0:
            try:
                trade=simulate_trade(bars,i+1,side,risk,asset_class)
            except ValueError:
                rejected+=1; i+=1; continue
            if trade is None:
                busy[side]=len(bars);i+=1;continue
            if i+1<split<=trade['exit_index']:
                busy[side]=split-1;i+=1;continue
            trade['signal_time']=bars[i]['end']
            trades.append(trade);busy[side]=trade['exit_index'];i+=1
        else:
            i+=1
    boundary=bars[split]['start'] if split<len(bars) else math.inf
    result=dict(as_of=now,strategy_id=STRATEGY_ID,
        rules='20-bar breakout; 1.5x median volume; ADX>=22, RSI/MACD direction; '+('as-of 15m confirmation; ' if confirmed else 'UNCONFIRMED hourly comparison; ')+'next open, prior ATR stop, net 2R target, 24-bar timeout',
        cost_per_side=COSTS[asset_class],split_index=split,rejected_entries=rejected,missing_confirmation=missing_confirmation,
        coverage=dict(start=bars[start_index]['start'] if start_index<len(bars) else None,end=bars[stop_index-1]['end'] if eligible_indices else None,hourly_bars=len(eligible_indices),confirmation_bars=len(quarters)),
        rule_coverage=dict(hourly_breakout=True,confirmation_15m_replayed=bool(confirmed and eligible_indices)),
        strategy_scope='confirmed_trend_breakout' if confirmed else 'exploratory_hourly_base_pattern',
        train=metrics([t for t in trades if t['side']=='LONG' and t['entry_time']<boundary]),
        holdout=metrics([t for t in trades if t['side']=='LONG' and t['entry_time']>=boundary]),
        short_research=dict(train=metrics([t for t in trades if t['side']=='SHORT' and t['entry_time']<boundary]),
            holdout=metrics([t for t in trades if t['side']=='SHORT' and t['entry_time']>=boundary]),
            note='Research only; borrow, financing and contract economics are not validated'),
        forward_paper=dict(closed_trades=[]),exploratory=asset_class=='commodities')
    result['holdout']['uncertainty']=grouped_expectancy(result['holdout']['trade_log'])
    result['ready'],result['reasons']=readiness(result)
    if result['exploratory']:
        result['ready']=False;result['reasons'].append('continuous futures require dated contract economics')
    return result
