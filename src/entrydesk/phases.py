"""Per-timeframe phases shown with each signal: 4H context, 1H setup, 15M execution.

4H is display context only; it is not an entry rule of trend-breakout-v2.
"""
from .factors import _atr_adx

FOUR_HOURS = 4 * 3600
HOURLY_CHECKS = ('breakout', 'volume', 'adx', 'momentum')


def _four_hour(bars_1h):
    """Completed UTC 4-hour buckets (00, 04, 08 ... UTC) built from completed hourly bars."""
    if not bars_1h:
        return []
    last_end, buckets = bars_1h[-1]['end'], {}
    for b in bars_1h:
        buckets.setdefault(b['start'] // FOUR_HOURS, []).append(b)
    out = []
    for key in sorted(buckets):
        end = (key + 1) * FOUR_HOURS
        if end > last_end:
            continue
        group = buckets[key]
        out.append(dict(start=key * FOUR_HOURS, end=end, open=group[0]['open'], close=group[-1]['close'],
                        high=max(b['high'] for b in group), low=min(b['low'] for b in group)))
    return out


def _ema20(bars):
    out = [bars[0]['close']]
    for b in bars[1:]:
        out.append(out[-1] + 2 / 21 * (b['close'] - out[-1]))
    return out


def _range(bars):
    """High/low of the 20 bars before the latest one."""
    prior = bars[-21:-1]
    return max(b['high'] for b in prior), min(b['low'] for b in prior)


def _h4(bars_1h):
    bars = _four_hour(bars_1h)
    if len(bars) < 35:
        return dict(phase='UNKNOWN', reason='fewer than 35 completed 4-hour bars')
    _, adx = _atr_adx(bars)
    ema = _ema20(bars)[-1]
    last = bars[-1]
    high, low = _range(bars)
    phase = 'RANGE' if adx is None or adx < 20 else 'TREND_UP' if last['close'] > ema else 'TREND_DOWN'
    position = 'ABOVE' if last['close'] > high else 'BELOW' if last['close'] < low else 'INSIDE'
    return dict(phase=phase, position=position, adx=adx, ema20=ema, range_high=high, range_low=low,
                close=last['close'], bar_end=last['end'])


def phases(bars_1h, checks, side, has_entry):
    """`checks` are the setup_evidence checks; `side` is the qualified hourly pattern side or None."""
    passed = {c['id']: c['passed'] for c in checks}
    count = sum(bool(passed.get(k)) for k in HOURLY_CHECKS)
    h1 = ('BREAKOUT_' + side if side else 'BREAKOUT_UNQUALIFIED' if passed.get('breakout') else 'NO_SETUP')
    if not side:
        m15 = 'WAIT'
    elif not passed.get('hourly_fresh'):
        m15 = 'EXPIRED'
    elif not passed.get('confirmation'):
        m15 = 'UNCONFIRMED'
    else:
        m15 = 'READY' if has_entry and passed.get('quote_fresh') else 'CONFIRMED'
    return dict(h4=_h4(bars_1h), h1=dict(phase=h1, passed=count, total=len(HOURLY_CHECKS)), m15=dict(phase=m15))


CHART_BARS = dict(m15=96, h1=120, h4=90)  # 24 hours, 5 days, 15 days


def charts(bars_1h, bars_15m, trade):
    """Close series per timeframe plus the levels the phases use; `trade` may hold entry/stop/target."""
    def series(bars, n):
        tail = bars[-n:]
        return dict(times=[b['end'] for b in tail], close=[b['close'] for b in tail])
    out = dict(m15=series(bars_15m, CHART_BARS['m15']), h1=series(bars_1h, CHART_BARS['h1']))
    h1_levels = {}
    if len(bars_1h) >= 21:
        high, low = _range(bars_1h)
        h1_levels = dict(range_high=high, range_low=low)
    out['h1']['levels'] = h1_levels
    out['m15']['levels'] = dict(h1_levels, **{k: trade[k] for k in ('entry', 'stop', 'target') if trade.get(k) is not None})
    bars_4h = _four_hour(bars_1h)
    out['h4'] = series(bars_4h, CHART_BARS['h4'])
    out['h4']['ema20'] = _ema20(bars_4h)[-CHART_BARS['h4']:] if bars_4h else []
    high, low = _range(bars_4h) if len(bars_4h) >= 21 else (None, None)
    out['h4']['levels'] = dict(range_high=high, range_low=low) if high is not None else {}
    return out
