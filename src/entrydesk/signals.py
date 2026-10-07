"""Candidate pattern and fail-closed paper readiness gates."""
import math
from .phases import charts, phases
from .validation import (COSTS, FUTURES_PROXIES, STRATEGY_ID, confirmation, futures_unverified, pattern,
                         readiness, target_price, pattern_evidence)


def evaluate(bundle, now, validation=None):
    result = _evaluate(bundle, now, validation)
    evidence = result.get('setup_evidence') or {}
    bars = bundle.get('bars_1h') if isinstance(bundle.get('bars_1h'), list) else []
    try:
        result['phases'] = phases(bars, evidence.get('checks', []), result.get('side'),
                                    result.get('entry') is not None and (result.get('net_rr') or 0) >= 2)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result['phases'] = dict(error=str(exc))
    if bundle.get('symbol') in FUTURES_PROXIES:
        result['label'] = FUTURES_PROXIES[bundle['symbol']]
        quarter = bundle.get('bars_15m') if isinstance(bundle.get('bars_15m'), list) else []
        try:
            result['charts'] = charts(bars, quarter, result)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            result['charts'] = dict(error=str(exc))
    return result


def _evaluate(bundle, now, validation=None):
    from .factors import build_factors, validate_bars, validate_quote
    result = {key: bundle.get(key) for key in ('symbol', 'asset_class', 'source')}
    result.update(strategy_id=STRATEGY_ID,as_of=now, state='WATCHING', side=None, entry=None, stop=None, target=None,
                  net_rr=None, score=None, factors={}, reasons=[], validation=validation or {})
    reasons = result['reasons']
    try:
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError('finite observation time required')
        if bundle.get('quote') is not None and not isinstance(bundle['quote'], dict):
            raise ValueError('quote must be an observation object or null')
        bars, confirm = bundle.get('bars_1h', []), bundle.get('bars_15m', [])
        validate_bars(bars, now)
        validate_bars(confirm, now)
        if len(bars) < 60:
            raise ValueError('60 completed hourly candles required')
        reasons.extend('provider: ' + str(warning) for warning in bundle.get('errors', []))
        if bundle.get('stale'):
            reasons.append('cached observations are stale')
        confirm=[b for b in confirm if b['end']<=bars[-1]['end']]
        factors = build_factors(bars, confirm[-96:])
        result['signal_time']=bars[-1]['end']
        result.update(factors=factors, score=factors.get('composite_alpha_score'))
        evidence = pattern_evidence(bars, factors)
        quote = bundle.get('quote') or {}
        entry, observed = quote.get('price'), quote.get('time')
        quote_fresh = all(not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)
                          for x in (entry, observed)) and entry > 0 and 0 <= now - observed <= 120
        evidence.update(hourly_end=bars[-1]['end'], quote_time=observed if isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(observed) else None)
        evidence['checks'].extend([
            dict(id='confirmation', label='Completed 15-minute confirmation',
                 passed=confirmation(bars, confirm, evidence['price_side']), value=None,
                 requirement='15m close confirms direction at the hourly signal time'),
            dict(id='hourly_fresh', label='Hourly signal freshness',
                 passed=now - bars[-1]['end'] <= 75 * 60, value=now - bars[-1]['end'], requirement='<= 4500 seconds'),
            dict(id='quote_fresh', label='Actual quote freshness', passed=quote_fresh,
                 value=now - observed if evidence['quote_time'] is not None else None, requirement='<= 120 seconds'),
        ])
        result['setup_evidence'] = evidence
        side = pattern(bars, factors)
        if not side:
            reasons.append('fixed breakout/volume/ADX/RSI/MACD predicates not present')
            return result
        result.update(side=side, state='CANDIDATE')
        if side == 'SHORT' and bundle.get('asset_class') in ('stocks', 'crypto'):
            reasons.append('short borrow availability and financing costs are unverified')
        if now - bars[-1]['end'] > 75 * 60:
            reasons.append('hourly breakout candle older than 75 minutes')
        sign = 1 if side == 'LONG' else -1
        prior_atr = build_factors(bars[:-1], [])['volatility_channel'].get('atr_1h')
        if isinstance(prior_atr, (int, float)) and math.isfinite(prior_atr) and prior_atr > 0:
            reference = bars[-1]['close']
            cost = COSTS[bundle['asset_class']]
            reference_stop = reference - sign * prior_atr
            reference_target = target_price(reference, prior_atr, side, cost)
            valid_reference, _, _ = validate_quote('BUY_LONG' if sign == 1 else 'SELL_SHORT', reference, reference_target, reference_stop)
            if valid_reference:
                result['reference_levels'] = {'entry': reference, 'stop': reference_stop,
                    'target': reference_target,
                    'net_rr': (sign * (reference_target - reference) - cost * (reference + reference_target)) / (prior_atr + cost * (reference + reference_stop)),
                    'cost_per_side': cost, 'signal_time': bars[-1]['end'],
                    'basis': 'completed hourly close; non-executable'}
        if not confirmation(bars,confirm,side):
            reasons.append('completed 15-minute breakout confirmation missing')
        if not quote_fresh:
            reasons.append('actual quote missing or older than 120 seconds')
        else:
            atr = factors['volatility_channel'].get('atr_1h')
            if not isinstance(atr, (int, float)) or not math.isfinite(atr) or atr <= 0:
                reasons.append('positive prior ATR unavailable')
            else:
                # stop uses ATR from preceding candle, without breakout-range expansion
                prior = prior_atr
                if not isinstance(prior, (int, float)) or not math.isfinite(prior) or prior <= 0:
                    raise ValueError('positive prior ATR unavailable')
                cost = COSTS[bundle['asset_class']]
                stop, target = entry - sign * prior, target_price(entry, prior, side, cost)
                risk = prior + cost * (entry + stop)
                reward = sign * (target - entry) - cost * (entry + target)
                result.update(entry=entry, stop=stop, target=target, net_rr=reward / risk)
                valid, geometry_reason, _ = validate_quote('BUY_LONG' if sign == 1 else 'SELL_SHORT', entry, target, stop)
                if not valid or result['net_rr'] < 2:
                    reasons.append(geometry_reason or 'net reward/risk below 2')
                bid, ask = quote.get('bid'), quote.get('ask')
                if bid is None or ask is None or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in (bid, ask)) or ask < bid or (ask-bid) / entry > .005:
                    reasons.append('valid spread unavailable or wider than 0.5%')
        if bundle.get('asset_class') == 'stocks' and bundle.get('market_open') is not True:
            reasons.append('regular equity market closed or unknown')
        if futures_unverified(bundle.get('asset_class'), bundle.get('symbol')):
            reasons.append('continuous futures lack dated contract/roll/point-value economics')
        if bundle.get('stale') or bundle.get('errors'):
            reasons.append('provider errors or stale cached observations')
        if not bundle.get('source') or bundle.get('source_mismatch'):
            reasons.append('source identity missing or mismatched')
        ready, vetoes = readiness(validation, now)
        reasons.extend(vetoes)
        result['state'] = 'PAPER_READY' if ready and not reasons else 'BLOCKED'
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        reasons.append(str(exc))
        result['state'] = 'BLOCKED'
    return result
