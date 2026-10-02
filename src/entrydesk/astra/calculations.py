# Astra Quant Agent, pinned 78c0e4aa768511e888c392aa27de357b02aaf0f4; AGPL-3.0, see LICENSE.
# Selected pure functions; modified 2026-10-03 (RSI zero-loss fixes).
from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Tuple
from .math_utils import safe_float as _sf

MACD_FAST = 12

MACD_SLOW = 26

MACD_SIGNAL = 9

DIVERGENCE_LOOKBACK = 20

VWAP_WINDOW_15M = 96

VPVR_BUCKETS = 30

VALUE_AREA_SIGMA = 1.0

EXTREME_BAND_SIGMA = 2.0

def derive_series(raw_candles: Sequence[Sequence[Any]]
                  ) -> Tuple[List[float], List[float], List[float], List[float]]:
    """OKX newest-first 原始 K 线 → `(closes, highs, lows, vols)` **时间正序**。

    ⚠️ `reversed` 必须保留：忘了它不会抛异常，只会让所有指标按反向时间算。
    """
    chron = list(reversed(list(raw_candles)))
    closes = [_sf(c[4]) for c in chron]
    highs = [_sf(c[2]) for c in chron]
    lows = [_sf(c[3]) for c in chron]
    vols = [_sf(c[5]) for c in chron]
    return closes, highs, lows, vols

def macd_series(closes: Sequence[float], fast: int = MACD_FAST,
                slow: int = MACD_SLOW, signal: int = MACD_SIGNAL
                ) -> Tuple[List[float], List[float], List[float]]:
    """返回 `(dif, dea, hist)` 三条**完整序列**（用于背离检测）。

    与 `astra_backend.execution.calc_macd_histogram_acceleration` **同源同种子**
    （首值取 `prices[0]`），故其末值与该函数返回值逐位一致 ——
    这条一致性由测试钉住，防止两处漂移出两个不同的 MACD。
    """
    if not closes:
        return [], [], []
    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_sig = 2.0 / (signal + 1)

    fast_ema = _sf(closes[0])
    slow_ema = _sf(closes[0])
    dif: List[float] = []
    for p in closes:
        px = _sf(p)
        fast_ema = px * k_fast + fast_ema * (1 - k_fast)
        slow_ema = px * k_slow + slow_ema * (1 - k_slow)
        dif.append(fast_ema - slow_ema)

    dea: List[float] = []
    sig_ema = dif[0]
    hist: List[float] = []
    for m in dif:
        sig_ema = m * k_sig + sig_ema * (1 - k_sig)
        dea.append(sig_ema)
        hist.append(m - sig_ema)
    return dif, dea, hist

def detect_divergence(closes: Sequence[float], oscillator: Sequence[float],
                      lookback: int = DIVERGENCE_LOOKBACK, *, eps: float = 1e-9) -> str:
    """窗口内价格与振荡器（MACD 柱 / RSI）的**顶底背离**。

    算法（刻意简单、可解释、无参数魔法）：把最近 `lookback` 根二分，
    比较两半的极值点及其对应的振荡器值 ——

    - 价格**创更低低点**、振荡器低点却**抬高** ⇒ `BULLISH`（空头动能衰竭）；
    - 价格**创更高高点**、振荡器高点却**走低** ⇒ `BEARISH`（多头动能衰竭）。

    样本不足或数值退化一律返回 `NONE`（不猜）。
    """
    eff_lb = max(1, int(lookback)) if lookback is not None else DIVERGENCE_LOOKBACK
    n = min(len(closes), len(oscillator), eff_lb)
    if n < 6:
        return "NONE"
    px = [_sf(v) for v in closes[-n:]]
    osc = [_sf(v) for v in oscillator[-n:]]
    half = n // 2

    first_px, second_px = px[:half], px[half:]
    first_osc, second_osc = osc[:half], osc[half:]

    i_low_1 = min(range(len(first_px)), key=lambda i: first_px[i])
    i_low_2 = half + min(range(len(second_px)), key=lambda i: second_px[i])
    if px[i_low_2] < px[i_low_1] - eps and osc[i_low_2] > osc[i_low_1] + eps:
        return "BULLISH"

    i_high_1 = max(range(len(first_px)), key=lambda i: first_px[i])
    i_high_2 = half + max(range(len(second_px)), key=lambda i: second_px[i])
    if px[i_high_2] > px[i_high_1] + eps and osc[i_high_2] < osc[i_high_1] - eps:
        return "BEARISH"
    return "NONE"

def classify_macd_momentum_state(macd_hist: Optional[float],
                                 macd_accel: Optional[float]) -> str:
    """MACD 柱与加速度组成的四态动能（供形态与提示词直接引用）。

    ⚠️ 缺失（`None`）⇒ `INSUFFICIENT_DATA`，**不许**退化成 `NEUTRAL`
    —— 那会被读成"真实的中性动量"（2026-10「不许假数据」审计）。
    """
    if macd_hist is None or macd_accel is None:
        return "INSUFFICIENT_DATA"
    h = _sf(macd_hist)
    a = _sf(macd_accel)
    if h > 0:
        return "BULL_EXPANDING" if a > 0 else "BULL_EXHAUSTING"
    if h < 0:
        return "BEAR_EXPANDING" if a < 0 else "BEAR_EXHAUSTING"
    return "NEUTRAL"

def compute_macd_factors(closes_1h: Sequence[float], price: float = 0.0) -> Dict[str, Any]:
    """1H MACD 因子块（柱、加速度、四态、顶底背离）。

    ## 为什么要输出"占现价 %"（2026-10 实盘暴露的展示事故）

    MACD 柱/加速度都是**价格单位**的量：BTC 柱=27.88，而 ARB 柱=−1.8e−05。
    前端按两位小数渲染 ⇒ ARB/DOGE 显示成 `-0.00 / 0.00`，看上去像"没有动能"
    （实盘截图就是这样）。而两者其实是同一量级的信息（ARB 柱/价 = −0.0089%）。

    ⇒ 同时给出**归一化**口径 `macd_hist_pct` / `macd_accel_pct`（柱 ÷ 现价 × 100），
    使 6 个标的可横向比较、且不受价格量级影响。价格缺失（≤0）时归一化键给 `None`
    —— 与全仓"缺失即缺失"同纪律，不用 0 冒充。

    ⚠️ **K 线不足时不许给 0**（2026-10 实测踩到）：MACD(12,26,9) 需要
    `slow + signal = 35` 根收盘价；调用方若只取 24 根，原实现会静默返回
    「柱=0、加速度=0、态=NEUTRAL」—— 那会被下游读成**真实的中性动量**
    （实盘快照里就是这样：BTC 1H MACD 恒为 0，而 RSI 正常）。
    现在改为显式缺失：数值键 `None`、状态 `INSUFFICIENT_DATA`。
    """
    dif, dea, hist = macd_series(closes_1h)
    px = _sf(price)
    if len(hist) < MACD_SLOW + MACD_SIGNAL:
        return {
            "macd_dif": None, "macd_dea": None, "macd_hist": None, "macd_accel": None,
            "macd_hist_pct": None, "macd_accel_pct": None,
            "macd_momentum_state": "INSUFFICIENT_DATA",
            "macd_divergence": "INSUFFICIENT_DATA",
        }
    accel = hist[-1] - hist[-2]
    return {
        "macd_dif": round(dif[-1], 6),
        "macd_dea": round(dea[-1], 6),
        "macd_hist": round(hist[-1], 6),
        "macd_accel": round(accel, 6),
        "macd_hist_pct": (round(hist[-1] / px * 100.0, 4) if px > 0 else None),
        "macd_accel_pct": (round(accel / px * 100.0, 4) if px > 0 else None),
        "macd_momentum_state": classify_macd_momentum_state(hist[-1], accel),
        "macd_divergence": detect_divergence(closes_1h, hist),
    }

def classify_rsi_zone(rsi: float, trend: str) -> str:
    """情境自适应 RSI 区间（静态 30/70 在单边趋势里必然失效）。

    - 多头大势：`38~52` 回踩低吸区 / `52~72` 健康运行区 / `>75` 超买禁追区；
    - 空头大势：`46~62` 反弹做空区 / `28~46` 健康运行区 / `<25` 超卖禁追区；
    - 箱体震荡：`<=32` 超跌区 / `>=68` 超买区 / 其余中性。
    """
    if rsi is None:
        return "INSUFFICIENT_DATA"      # 缺失不许退化成"中性区间"
    r = _sf(rsi)
    t = str(trend or "").upper()
    if "BULL" in t:
        if r > 75.0:
            return "OVERBOUGHT_NO_CHASE"
        if 52.0 <= r <= 72.0:
            return "BULL_HEALTHY"
        if 38.0 <= r < 52.0:
            return "BULL_PULLBACK_BUY"
        return "NEUTRAL"
    if "BEAR" in t:
        if r < 25.0:
            return "OVERSOLD_NO_CHASE"
        if 28.0 <= r <= 46.0:
            return "BEAR_HEALTHY"
        if 46.0 < r <= 62.0:
            return "BEAR_RALLY_SELL"
        return "NEUTRAL"
    if r <= 32.0:
        return "RANGE_OVERSOLD"
    if r >= 68.0:
        return "RANGE_OVERBOUGHT"
    return "NEUTRAL"

def compute_rsi_factors(closes_1h: Sequence[float], closes_15m: Sequence[float],
                        trend: str) -> Dict[str, Any]:
    """1H/15M RSI(14) + 情境区间 + 1H 顶底背离。

    RSI 数值沿用门面既有口径（最近 14 根简单均值）——**不引入第二套 RSI 定义**。
    """
    def _rsi(closes: Sequence[float]) -> Optional[float]:
        vals = [_sf(c) for c in closes]
        if len(vals) < 15:
            # ★ 原实现返回 50.0 ⇒ 提示词显示"RSI=50.0 (中性)"，而打分侧
            #   `rsi >= 50 ⇒ +15` 会因此**凭空加 15 分趋势分**（2026-10 审计）。
            return None
        diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        gains = [d if d > 0 else 0.0 for d in diffs[-14:]]
        losses = [-d if d < 0 else 0.0 for d in diffs[-14:]]
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rs = (avg_g / avg_l) if avg_l > 0 else None
        return round(100.0 - (100.0 / (1.0 + rs)), 1) if rs is not None else (100.0 if avg_g > 0 else 50.0)

    rsi_1h = _rsi(closes_1h)
    rsi_15m = _rsi(closes_15m)
    rsi_series: List[float] = []
    vals = [_sf(c) for c in closes_1h]
    for end in range(15, len(vals) + 1):
        seg = vals[:end]
        diffs = [seg[i] - seg[i - 1] for i in range(1, len(seg))]
        gains = [d if d > 0 else 0.0 for d in diffs[-14:]]
        losses = [-d if d < 0 else 0.0 for d in diffs[-14:]]
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rs = (avg_g / avg_l) if avg_l > 0 else None
        rsi_series.append(100.0 - (100.0 / (1.0 + rs)) if rs is not None else (100.0 if avg_g > 0 else 50.0))
    return {
        "rsi_1h": rsi_1h,
        "rsi_15m": rsi_15m,
        "rsi_zone": classify_rsi_zone(rsi_1h, trend),
        "rsi_divergence": (detect_divergence(vals, rsi_series) if rsi_series
                           else "INSUFFICIENT_DATA"),
    }

def compute_vwap_volume_profile(raw_candles_15m: Sequence[Sequence[Any]], price: float,
                                *, window: int = VWAP_WINDOW_15M,
                                buckets: int = VPVR_BUCKETS) -> Dict[str, Any]:
    """24H 滚动 VWAP 统计分布 + VPVR 筹码密集峰。

    - VWAP / σ 用**典型价** `(h+l+c)/3` 与成交量加权；
    - 价值区 `VAH/VAL = VWAP ± 1.0σ`（约 70% 成交量）、极值带 `± 2.0σ`（约 95%）；
    - POC = 把窗口高低区间等分 `buckets` 桶后**成交量最大的桶中点**（主力成本峰）。
    """
    closes, highs, lows, vols = derive_series(raw_candles_15m)
    n = min(len(closes), window)
    # ★ 缺失 ⇒ `None`（提示词渲染 `--`）：0.0 的 VWAP/POC 会被读成"价位在 0"
    #   或"无筹码峰"，`NEUTRAL` 会被读成"位置中性"——都是假结论。
    out: Dict[str, Any] = {
        "vwap_24h": None, "vwap_sigma_pct": None, "vah": None, "val": None,
        "vpvr_poc": None, "value_area_position": "INSUFFICIENT_DATA",
        "vwap_extreme_band": "INSUFFICIENT_DATA",
    }
    if n < 10:
        return out
    closes, highs, lows, vols = closes[-n:], highs[-n:], lows[-n:], vols[-n:]
    typ = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    total_v = sum(vols)
    if total_v <= 0:
        return out

    vwap = sum(typ[i] * vols[i] for i in range(n)) / total_v
    var = sum(vols[i] * (typ[i] - vwap) ** 2 for i in range(n)) / total_v
    sigma = var ** 0.5
    sigma_pct = (sigma / vwap * 100.0) if vwap > 0 else 0.0

    lo, hi = min(lows), max(highs)
    poc = 0.0
    if hi > lo and buckets > 0:
        width = (hi - lo) / buckets
        hist = [0.0] * buckets
        for i in range(n):
            idx = int((typ[i] - lo) / width)
            idx = 0 if idx < 0 else (buckets - 1 if idx >= buckets else idx)
            hist[idx] += vols[i]
        best = max(range(buckets), key=lambda k: hist[k])
        poc = lo + (best + 0.5) * width

    px = _sf(price)
    pos = "NEUTRAL"
    band = "NONE"
    if vwap > 0 and sigma > 0 and px > 0:
        z = (px - vwap) / sigma
        if z >= EXTREME_BAND_SIGMA:
            band = "UPPER_EXTREME"
        elif z <= -EXTREME_BAND_SIGMA:
            band = "LOWER_EXTREME"
        elif z >= VALUE_AREA_SIGMA:
            band = "UPPER_VALUE_AREA"
        elif z <= -VALUE_AREA_SIGMA:
            band = "LOWER_VALUE_AREA"
        else:
            band = "INSIDE_VALUE_AREA"
        if px > vwap:
            pos = "ABOVE_VWAP"
        elif px < vwap:
            pos = "BELOW_VWAP"

    return {
        "vwap_24h": round(vwap, 6),
        "vwap_sigma_pct": round(sigma_pct, 4),
        "vah": round(vwap + VALUE_AREA_SIGMA * sigma, 6),
        "val": round(vwap - VALUE_AREA_SIGMA * sigma, 6),
        "vpvr_poc": round(poc, 6),
        "value_area_position": pos,
        "vwap_extreme_band": band,
    }

OBI_STRONG_BID_PCT = 20.0
OBI_STRONG_ASK_PCT = -20.0

def compute_depth_factors(depth: Optional[Dict[str, Any]], price: float,
                          *, top_n: int = 20,
                          min_multi_order_levels: int = 3) -> Dict[str, Any]:
    """订单簿失衡度 OBI / Top5 与 Top20 深度比 / 有效点差 bps。

    ## ⚠️ 2026-10 实测：盘口**触价档**会被单笔可撤挂单支配（但极端失衡本身可能为真）

    连续三次抓 BTC-USDT-SWAP Top20 盘口（间隔 2s），拿到的买一是
    **574 → 3.44 → 89.6 张**（同一价位、numOrders=1），而买 2~5 档始终
    不足 5 张 —— 触价档在几秒内跳动两个数量级，OBI 也随之从 +14% 翻到 −94%。

    同一次采样里卖侧却**逐档都厚**（卖一 897 张 n=57、其余多档 75~226 张），
    全簿合计 买 17.7 张 vs 卖 1786 张 ⇒ **−95%~−98% 的极端 OBI 是真实状态**，
    不能一律当噪音丢掉。所以这里的处理是"分开看"，而不是"把极端值砍掉"：

    1. `obi_pct`（原始 Top20）与 `depth_ratio_20` 照给（诊断/展示用）；
    2. **`obi_robust_pct`**：只累计 `numOrders >= min_multi_order_levels` 的档位
       —— 单笔挂单是可秒撤的报价，不计入"真实厚度"，用来抵消**触价档**
       被单笔挂单支配带来的抖动；
    3. `depth_reliable`：两侧各有 ≥3 个多笔档才为 True。为 False（例如全簿
       只有单笔挂单、或盘口没取回）时，下游（打分/信号）**必须把 OBI 当缺失**，
       不许当 0 或中性用。

    故本函数改为**双口径**并显式标注可信度：

    1. `obi_pct`（原始 Top20）与 `depth_ratio_20` 仍然给（诊断/展示用）；
    2. **`obi_robust_pct`**：只统计 `numOrders >= min_multi_order_levels` 的档位
       —— OKX 每档都返回 `numOrders`，单笔挂单（numOrders=1）是可秒撤的报价，
       不计入"真实厚度"；
    3. `depth_reliable`：稳健口径**两侧各有 ≥3 个多笔档**才为 True。
       为 False 时下游（打分/信号）**必须把 OBI 当作缺失**，不许当 0 或中性用。
    """
    # ★ 缺失 ⇒ `None`（提示词渲染 `--`）：1.0 会被读成"买卖深度均衡"、
    #   0.0 会被读成"零失衡"，两者都是**结论**而非缺失。
    out: Dict[str, Any] = {
        "bid_ask_depth_ratio": None, "depth_ratio_20": None, "obi_pct": None,
        "obi_robust_pct": None, "depth_reliable": False,
        "depth_note": "盘口未取回", "spread_bps": None,
        "depth_bias": "INSUFFICIENT_DATA",
    }
    if not isinstance(depth, dict):
        return out
    bids = [b for b in (depth.get("bids") or []) if isinstance(b, (list, tuple)) and len(b) >= 2]
    asks = [a for a in (depth.get("asks") or []) if isinstance(a, (list, tuple)) and len(a) >= 2]
    if not bids or not asks:
        out["depth_note"] = "盘口单侧为空"
        return out

    def _sz(rows: Sequence[Sequence[Any]], n: int) -> float:
        return sum(_sf(r[1]) for r in rows[:n])

    def _robust(rows: Sequence[Sequence[Any]]) -> Tuple[float, int]:
        """只累计**多笔档**（`numOrders >= min_multi_order_levels`）的张数与档数。"""
        total, levels = 0.0, 0
        for r in rows[:top_n]:
            n_orders = int(_sf(r[3])) if len(r) > 3 else 0
            if n_orders >= min_multi_order_levels:
                total += _sf(r[1])
                levels += 1
        return total, levels

    bid5, ask5 = _sz(bids, 5), _sz(asks, 5)
    bid20, ask20 = _sz(bids, top_n), _sz(asks, top_n)

    out["bid_ask_depth_ratio"] = round(bid5 / ask5, 4) if ask5 > 0 else None
    out["depth_ratio_20"] = round(bid20 / ask20, 4) if ask20 > 0 else None
    denom = bid20 + ask20
    if denom > 0:
        obi = (bid20 - ask20) / denom * 100.0
        out["obi_pct"] = round(obi, 2)
        # 有可算的 OBI ⇒ 才允许下"均衡"这个结论（缺失时保持 INSUFFICIENT_DATA）
        out["depth_bias"] = "NEUTRAL"
        if obi >= OBI_STRONG_BID_PCT:
            out["depth_bias"] = "STRONG_BID"
        elif obi <= OBI_STRONG_ASK_PCT:
            out["depth_bias"] = "STRONG_ASK"

    rb, rb_levels = _robust(bids)
    ra, ra_levels = _robust(asks)
    if rb + ra > 0:
        out["obi_robust_pct"] = round((rb - ra) / (rb + ra) * 100.0, 2)
    if rb_levels >= 3 and ra_levels >= 3 and rb > 0 and ra > 0:
        out["depth_reliable"] = True
        out["depth_note"] = ""
    else:
        out["depth_note"] = (
            f"盘口厚度由单笔可撤挂单支配（多笔档 买{rb_levels}/卖{ra_levels} < 3）"
            "⇒ OBI 不可作为方向证据")

    best_bid = _sf(bids[0][0])
    best_ask = _sf(asks[0][0])
    px = _sf(price) or ((best_bid + best_ask) / 2.0)
    if best_bid > 0 and best_ask > 0 and px > 0:
        out["spread_bps"] = round((best_ask - best_bid) / px * 10000.0, 4)
    return out
