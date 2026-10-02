"""Fixed chronological research simulation; no orders or inferred paper evidence."""
import math
import statistics
import time

COSTS = {'stocks': .0005, 'crypto': .0015, 'commodities': .001}


def pattern(bars, factors=None):
    if len(bars) < 60:
        return None
    prior, last = bars[-21:-1], bars[-1]
    median = statistics.median(b['volume'] for b in prior)
    if median <= 0 or last['volume'] < 1.5 * median:
        return None
    recommendation = factors.get('signal_recommendation') if factors is not None else None
    if last['close'] > max(b['high'] for b in prior) and (factors is None or recommendation == 'BUY_LONG'):
        return 'LONG'
    if last['close'] < min(b['low'] for b in prior) and (factors is None or recommendation == 'SELL_SHORT'):
        return 'SHORT'
    return None


def target_price(entry, risk, side, cost):
    """Solve net reward = 2 * net stop loss, including exit-price costs."""
    sign = 1 if side == 'LONG' else -1
    stop = entry - sign * risk
    net_risk = risk + cost * (entry + stop)
    return (sign * entry + cost * entry + (2 + 1e-10) * net_risk) / (sign - cost)


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


def backtest(bars, asset_class):
    from .factors import build_factors, validate_bars
    from .data import validate_interval
    validate_bars(bars, max((b.get('end', 0) for b in bars), default=0))
    validate_interval(bars, 3600)
    split = int(len(bars) * .8)
    trades, i, rejected = [], 59, 0
    while i < len(bars) - 1:
        # Price/volume veto is cheap; compute recursive full-history indicators only for breakouts.
        if not pattern(bars[max(0, i-59):i+1]):
            i += 1
            continue
        # ponytail: full-prefix factors cost O(K*N) for K breakouts; incremental adapter if deadlines routinely fail.
        prefix = bars[:i+1]
        factors = build_factors(prefix, [])
        side = pattern(prefix, factors)
        risk = build_factors(prefix[:-1], []).get('volatility_channel', {}).get('atr_1h') if side else None
        if side and isinstance(risk, (int, float)) and math.isfinite(risk) and risk > 0:
            try:
                trade = simulate_trade(bars, i+1, side, risk, asset_class)
            except ValueError:
                rejected += 1
                i += 1
                continue
            if trade is None:
                break  # terminal open positions are not fabricated closed observations
            # Do not let a training position consume the untouched holdout.
            if i+1 < split <= trade['exit_index']:
                i = split - 1
                continue
            trades.append(trade)
            i = trade['exit_index']
        else:
            i += 1
    result = {'as_of': bars[-1]['end'] if bars else 0, 'rules': 'UNCONFIRMED hourly base pattern; no 15m replay. 20-bar breakout, 1.5x preceding median volume, Astra direction; next open, 24-bar timeout',
              'cost_per_side': COSTS[asset_class], 'split_index': split, 'rejected_entries': rejected,
              'rule_coverage': {'hourly_breakout': True, 'confirmation_15m_replayed': False},
              'strategy_scope': 'exploratory_hourly_base_pattern',
              'train': metrics([t for t in trades if t['entry_time'] < (bars[split]['start'] if split < len(bars) else math.inf)]),
              'holdout': metrics([t for t in trades if split < len(bars) and t['entry_time'] >= bars[split]['start']]),
              'forward_paper': {'closed_trades': []}, 'exploratory': asset_class == 'commodities'}
    result['ready'], result['reasons'] = readiness(result)
    if result['exploratory']:
        result['ready'] = False
        result['reasons'].append('continuous futures require dated contract economics')
    return result
