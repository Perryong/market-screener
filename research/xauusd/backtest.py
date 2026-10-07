"""XAUUSD breakout-retest backtest (mechanical version of the top-down plan).

Rules, per timeframe bar (H4 from GC=F hourly, or daily):
  range     prior 20-bar high/low
  breakout  close beyond the range with volume >= 1.5x prior 20-bar median
  entry     limit at the broken level within RETEST bars (fills at the open if it gaps through)
  stop      1 ATR(14) back inside the range; target 2R; time exit after HOLD bars
  costs     COST_PCT of price per side, charged in R
Variants: none | align (weekly close > SMA20 and daily close > EMA50, mirrored for
shorts, using only completed higher-timeframe bars) | align+adx (also daily ADX14 >= 20).
Same-bar stop/target ambiguity resolves to the stop. One position at a time.

uv run --with matplotlib python research/xauusd/backtest.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
LOOKBACK, VOL_RATIO, ATR_N, RR, COST_PCT = 20, 1.5, 14, 2.0, 0.0003
VARIANTS = ('none', 'align', 'align+adx')


def load(name):
    d = pd.read_csv(HERE / f'gc_{name}.csv', index_col=0)
    d.index = pd.to_datetime(d.index, utc=True)
    return d[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()


def atr(d, n=ATR_N):
    pc = d.Close.shift()
    tr = pd.concat([d.High - d.Low, (d.High - pc).abs(), (d.Low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def adx(d, n=14):
    up, dn = d.High.diff(), -d.Low.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    a = atr(d, n)
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / a
    return (100 * (pdi - mdi).abs() / (pdi + mdi)).ewm(alpha=1 / n, adjust=False).mean()


def context(daily, index):
    """Higher-timeframe bias known at each bar: only bars completed before it (shift 1)."""
    w = daily.resample('W-FRI').agg({'Close': 'last'}).dropna()
    week_bull = (w.Close > w.Close.rolling(20).mean()).shift(1)
    week_bear = (w.Close < w.Close.rolling(20).mean()).shift(1)
    ema50 = daily.Close.ewm(span=50, adjust=False).mean()
    ctx = pd.DataFrame({'day_bull': (daily.Close > ema50).shift(1),
                        'day_bear': (daily.Close < ema50).shift(1),
                        'trend': (adx(daily) >= 20).shift(1)})
    ctx['week_bull'] = week_bull.reindex(ctx.index, method='ffill')
    ctx['week_bear'] = week_bear.reindex(ctx.index, method='ffill')
    # Map each bar to the latest daily row strictly before its own calendar day.
    pos = ctx.index.searchsorted(index.normalize(), side='left') - 1
    out = ctx.iloc[np.clip(pos, 0, None)].astype('boolean').fillna(False).astype(bool)
    out.index = index
    out.loc[pos < 0] = False
    return out


def backtest(bars, ctx, variant, retest, hold):
    hi = bars.High.rolling(LOOKBACK).max().shift()
    lo = bars.Low.rolling(LOOKBACK).min().shift()
    vmed = bars.Volume.rolling(LOOKBACK).median().shift()
    a = atr(bars)
    O, H, L, C = (bars[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
    trades, i, n = [], LOOKBACK + ATR_N, len(bars)
    while i < n - 1:
        side = 0
        if bars.Volume.iat[i] >= VOL_RATIO * vmed.iat[i] > 0:
            side = 1 if C[i] > hi.iat[i] else -1 if C[i] < lo.iat[i] else 0
        if side and variant != 'none':
            c = ctx.iloc[i]
            ok = (c.week_bull and c.day_bull) if side > 0 else (c.week_bear and c.day_bear)
            side = side if ok and (variant == 'align' or c.trend) else 0
        if not side:
            i += 1
            continue
        level = hi.iat[i] if side > 0 else lo.iat[i]
        stop = level - side * a.iat[i]
        j, entry = i + 1, None
        while j < min(i + 1 + retest, n):  # wait for the retest
            if side > 0 and L[j] <= level and O[j] > stop:
                entry = min(O[j], level)
            elif side < 0 and H[j] >= level and O[j] < stop:
                entry = max(O[j], level)
            if entry is not None or (side > 0 and L[j] <= stop) or (side < 0 and H[j] >= stop):
                break
            j += 1
        if entry is None:
            i += 1
            continue
        risk = abs(entry - stop)
        target = entry + side * RR * risk
        exit_px, k = None, j
        while k < min(j + hold, n):
            # Entry bar: only the stop can be judged after the fill (path unknown); target from next bar.
            if (side > 0 and L[k] <= stop) or (side < 0 and H[k] >= stop):
                exit_px = stop if k == j or (side > 0 and O[k] > stop) or (side < 0 and O[k] < stop) else O[k]
                break
            if k > j and ((side > 0 and H[k] >= target) or (side < 0 and L[k] <= target)):
                exit_px = target if (side > 0 and O[k] < target) or (side < 0 and O[k] > target) else O[k]
                break
            k += 1
        if exit_px is None:
            k = min(j + hold, n) - 1
            exit_px = C[k]
        r = (side * (exit_px - entry) - COST_PCT * (entry + exit_px)) / risk
        trades.append(dict(signal=bars.index[i], entry_time=bars.index[j], exit_time=bars.index[k],
                           side=side, entry=entry, stop=stop, target=target, exit=exit_px, r=r))
        i = k + 1
    return pd.DataFrame(trades)


def stats(t):
    if t.empty:
        return dict(trades=0)
    r, eq = t.r, t.r.cumsum()
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return dict(trades=len(r), win_rate=(r > 0).mean(), expectancy_r=r.mean(), total_r=r.sum(),
                profit_factor=wins / losses if losses else np.inf,
                max_dd_r=(eq.cummax().clip(lower=0) - eq).max())


def run(bars, daily, retest, hold):
    ctx = context(daily, bars.index)
    split = bars.index[int(len(bars) * .7)]
    out = {}
    for v in VARIANTS:
        t = backtest(bars, ctx, v, retest, hold)
        out[v] = t
        for label, part in (('all', t), ('in-sample 70%', t[t.entry_time < split] if len(t) else t),
                            ('out-of-sample 30%', t[t.entry_time >= split] if len(t) else t)):
            s = stats(part)
            print(f'  {v:10} {label:18} ' + '  '.join(f'{k}={x:.2f}' if isinstance(x, float) else f'{k}={x}'
                                                    for k, x in s.items()))
    return out, split


def selfcheck():
    """Synthetic long: range 100-110, breakout bar, retest at 110, rally to target -> ~ +2R less costs."""
    idx = pd.date_range('2024-01-01', periods=60, freq='4h', tz='UTC')
    base = np.r_[np.tile([100, 110], 20), [115], [110.5], np.linspace(111, 140, 18)]
    b = pd.DataFrame({'Open': base, 'High': base + 1, 'Low': base - 1, 'Close': base,
                      'Volume': np.r_[np.ones(40), [5], np.ones(19)]}, index=idx)
    b.loc[idx[41], ['Open', 'High']] = 112, 112.5  # retest bar opens above 111, dips to 109.5
    t = backtest(b, pd.DataFrame(False, index=idx, columns=['week_bull']), 'none', 6, 30)
    assert len(t) == 1 and t.side[0] == 1 and t.entry[0] == 111, t
    assert abs(t.r[0] - (2 - COST_PCT * (t.entry[0] + t.exit[0]) / (t.entry[0] - t.stop[0]))) < 1e-9, t


def plot(h4, res_h4, split_h4, daily, res_d, split_d, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#0b0b0b', '#52514e', '#e4e3df'
    colors = dict(zip(VARIANTS, ('#2a78d6', '#eb6834', '#1baf7a')))
    good, bad = '#008300', '#e34948'
    plt.rcParams.update({'font.size': 10, 'axes.edgecolor': grid, 'axes.labelcolor': muted,
                         'xtick.color': muted, 'ytick.color': muted, 'axes.titlecolor': ink,
                         'axes.titleweight': 'bold', 'axes.titlelocation': 'left'})
    fig, ax = plt.subplots(3, 1, figsize=(13, 13), gridspec_kw={'height_ratios': [3, 2, 2]})
    best = 'align'
    p = ax[0]
    p.plot(h4.index, h4.Close, color=muted, lw=1)
    t = res_h4[best]
    for _, x in t.iterrows():
        c = good if x.r > 0 else bad
        p.scatter(x.entry_time, x.entry, marker='^' if x.side > 0 else 'v', s=60, color=c,
                  edgecolor='white', linewidth=1.5, zorder=3)
    p.scatter([], [], marker='^', color=good, label='Long, won'); p.scatter([], [], marker='^', color=bad, label='Long, lost')
    p.scatter([], [], marker='v', color=good, label='Short, won'); p.scatter([], [], marker='v', color=bad, label='Short, lost')
    p.set_title(f'Gold (GC=F) H4 close with "{best}" variant entries')
    p.set_ylabel('USD/oz')
    p.legend(loc='upper left', frameon=False, ncol=4)
    for a_, res, split, title in ((ax[1], res_h4, split_h4, 'H4 strategy: cumulative R after costs (last ~2 years)'),
                                  (ax[2], res_d, split_d, 'Same rules on daily bars since 2020: cumulative R after costs')):
        for v in VARIANTS:
            t = res[v]
            if t.empty:
                continue
            eq = t.r.cumsum()
            a_.step(t.exit_time, eq, where='post', color=colors[v], lw=2,
                    label=f'{v}: {len(t)} trades, {t.r.mean():+.2f}R/trade')
            a_.annotate(f'{eq.iat[-1]:+.1f}R', (t.exit_time.iat[-1], eq.iat[-1]), xytext=(4, 0),
                        textcoords='offset points', color=ink, va='center', fontsize=9)
        a_.axhline(0, color=muted, lw=1)
        a_.axvline(split, color=muted, lw=1, ls='--')
        a_.annotate('out-of-sample →', (split, 1), xycoords=('data', 'axes fraction'), xytext=(4, -12),
                    textcoords='offset points', color=muted, fontsize=9)
        a_.set_title(title)
        a_.set_ylabel('R (1R = initial risk)')
        a_.legend(loc='upper left', frameon=False)
    for a_ in ax:
        a_.grid(color=grid, lw=.6)
        a_.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    print('wrote', path)


if __name__ == '__main__':
    selfcheck()
    daily = load('1d')
    h1 = load('1h')
    h4 = h1.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last',
                                'Volume': 'sum'}).dropna()
    h4 = h4[h4.Volume > 0]
    print(f'H4 {h4.index[0]:%Y-%m-%d} → {h4.index[-1]:%Y-%m-%d}, {len(h4)} bars')
    res_h4, split_h4 = run(h4, daily, retest=6, hold=30)
    # Yahoo's GC=F daily volume is only real from 2020 (median ~100 contracts/day before).
    d = daily[daily.index >= '2020-01-01']
    print(f'Daily {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}, {len(d)} bars')
    res_d, split_d = run(d, daily, retest=5, hold=20)
    pd.concat({v: t for v, t in res_h4.items()}).to_csv(HERE / 'trades_h4.csv')
    plot(h4, res_h4, split_h4, d, res_d, split_d, HERE / 'backtest.png')
    sys.exit(0)
