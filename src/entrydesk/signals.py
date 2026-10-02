"""Candidate pattern and fail-closed paper readiness gates."""
import math
from .validation import COSTS, pattern, readiness, target_price


def evaluate(bundle, now, validation=None):
    from .factors import build_factors, validate_bars, validate_quote
    result = {key: bundle.get(key) for key in ('symbol', 'asset_class', 'source')}
    result.update(as_of=now, state='WATCHING', side=None, entry=None, stop=None, target=None,
                  net_rr=None, score=None, factors={}, reasons=[], validation=validation or {})
    reasons = result['reasons']
    try:
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError('finite observation time required')
        bars, confirm = bundle.get('bars_1h', []), bundle.get('bars_15m', [])
        validate_bars(bars, now)
        validate_bars(confirm, now)
        if len(bars) < 60:
            raise ValueError('60 completed hourly candles required')
        factors = build_factors(bars, confirm)
        result.update(factors=factors, score=factors.get('composite_alpha_score'))
        side = pattern(bars, factors)
        if not side:
            reasons.append('fixed breakout/volume/Astra direction not present')
            return result
        result.update(side=side, state='CANDIDATE')
        if now - bars[-1]['end'] > 75 * 60:
            reasons.append('hourly breakout candle older than 75 minutes')
        sign = 1 if side == 'LONG' else -1
        prior_atr = build_factors(bars[:-1], [])['volatility_channel'].get('atr_1h')
        if isinstance(prior_atr, (int, float)) and math.isfinite(prior_atr) and prior_atr > 0:
            reference = bars[-1]['close']
            result['reference_levels'] = {'entry': reference, 'stop': reference - sign * prior_atr,
                'target': target_price(reference, prior_atr, side, COSTS[bundle['asset_class']]),
                'basis': 'completed hourly close; non-executable'}
        level = max(b['high'] for b in bars[-21:-1]) if sign == 1 else min(b['low'] for b in bars[-21:-1])
        if not confirm or confirm[-1]['end'] < bars[-1]['end'] or sign * (confirm[-1]['close'] - level) <= 0:
            reasons.append('completed 15-minute breakout confirmation missing')
        quote = bundle.get('quote') or {}
        entry, observed = quote.get('price'), quote.get('time')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (entry, observed)) or entry <= 0 or not 0 <= now - observed <= 120:
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
        if bundle.get('asset_class') == 'commodities':
            reasons.append('continuous futures lack dated contract/roll/point-value economics')
        if bundle.get('stale') or bundle.get('errors'):
            reasons.append('provider errors or stale cached observations')
        if not bundle.get('source') or bundle.get('source_mismatch'):
            reasons.append('source identity missing or mismatched')
        ready, vetoes = readiness(validation)
        reasons.extend(vetoes)
        result['state'] = 'PAPER_READY' if ready and not reasons else 'BLOCKED'
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        reasons.append(str(exc))
        result['state'] = 'BLOCKED'
    return result
