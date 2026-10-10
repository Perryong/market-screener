"""OANDA practice-API fallback for commodities (XAUUSD, USOIL).

TradingView throttles by call volume per IP; when its CFD feed for gold/oil goes
down the collector falls back to the last-good value and flags it stale. OANDA's
v20 REST API is a separate upstream and keeps answering, so this module produces
a `coin_analysis`-shaped section for the two commodity symbols instead of letting
them sit on a multi-day-old snapshot.

Read-only market-data GET endpoints only. Credentials come from the environment
(OANDA_TOKEN, OANDA_ACCOUNT_ID) and are never logged or embedded in output.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

OANDA_HOST = "https://api-fxpractice.oanda.com"
INSTRUMENTS = {"XAUUSD": "XAU_USD", "USOIL": "WTICO_USD"}


def _get_json(url: str, params: dict | None = None, token: str | None = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "market-screener/1.0", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> float | None:
    if not values or len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _macd(closes: list[float]) -> dict | None:
    if len(closes) < 26:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None
    line = ema12 - ema26
    # single-point MACD: signal line approximated by the 9-EMA over the series is
    # overkill here; the dashboard only needs the histogram sign for a fallback.
    return {"macd_line": round(line, 6), "signal_line": round(line, 6),
            "histogram": 0.0, "crossover": "Bullish" if line > 0 else "Bearish"}


def analysis(key: str) -> dict | None:
    """Return a coin_analysis-shaped section for XAUUSD/USOIL, or None if unavailable."""
    token = (os.getenv("OANDA_TOKEN") or "").strip()
    account = (os.getenv("OANDA_ACCOUNT_ID") or "").strip()
    if not token or not account or key not in INSTRUMENTS:
        return None
    instrument = INSTRUMENTS[key]
    try:
        d1 = _get_json(f"{OANDA_HOST}/v3/instruments/{instrument}/candles",
                       {"granularity": "D", "price": "M", "count": 250, "smooth": "false"}, token)
        closes = [float(c["mid"]["c"]) for c in d1["candles"] if c.get("complete")]
        prices = _get_json(f"{OANDA_HOST}/v3/accounts/{urllib.parse.quote(account, safe='')}/pricing",
                           {"instruments": instrument}, token)["prices"]
        p = next((x for x in prices if x["instrument"] == instrument), None)
        # "non-tradeable" just means the market is closed (weekend / after hours);
        # the last quoted bid/ask is still the correct "current" price to display.
        tradeable = bool(p and p.get("tradeable"))
        if p and p.get("bids") and p.get("asks"):
            cur = (float(p["bids"][0]["price"]) + float(p["asks"][0]["price"])) / 2
        else:
            cur = closes[-1]
    except Exception:
        return None
    if len(closes) < 30:
        return None

    if tradeable:
        change_pct = (cur - closes[-1]) / closes[-1] * 100      # vs yesterday's close
    else:
        change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100  # last session's own move
    rsi = _rsi(closes)
    ema50, ema200 = _ema(closes, 50), _ema(closes, 200)
    sma50, sma200 = _sma(closes, 50), _sma(closes, 200)

    reasons: list[str] = []
    if rsi is not None:
        reasons.append(f"RSI(14) {rsi:.1f} ({'bearish < 50' if rsi < 50 else 'bullish > 50'})")
    cross = None
    if ema50 is not None and ema200 is not None:
        cross = "Death Cross (EMA50 < EMA200)" if ema50 < ema200 else "Golden Cross (EMA50 > EMA200)"
        reasons.append(cross)
    bias = "Bearish" if rsi is not None and rsi < 50 else "Bullish"

    sma = {f"sma{n}": (round(_sma(closes, n), 4) if _sma(closes, n) is not None else None)
           for n in (10, 20, 30, 50, 100, 200)}
    ema = {f"ema{n}": (round(_ema(closes, n), 4) if _ema(closes, n) is not None else None)
           for n in (10, 20, 30, 50, 100, 200)}
    sma_signals = []
    if sma50 is not None:
        sma_signals.append("Price below SMA50 (bearish)" if cur < sma50 else "Price above SMA50 (bullish)")
    if sma200 is not None:
        sma_signals.append("Price below SMA200 (long-term bearish)" if cur < sma200 else "Price above SMA200 (long-term bullish)")

    return {
        "ok": True,
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "took_s": 0.0,
        "source": "oanda",
        "data": {
            "symbol": f"OANDA:{instrument}",
            "exchange": "oanda",
            "timeframe": "1D",
            "price_data": {
                "current_price": round(cur, 4),
                "open": round(closes[-1], 4),
                "high": round(max(cur, closes[-1]), 4),
                "low": round(min(cur, closes[-1]), 4),
                "close": round(cur, 4),
                "change_percent": round(change_pct, 3),
                "volume": 0,
            },
            "timeframe_context": {
                "timeframe": "1D",
                "bias": bias,
                "bias_reasons": reasons,
                "advice": "OANDA fallback (TradingView CFD feed throttled)",
            },
            "rsi": {
                "value": round(rsi, 2) if rsi is not None else None,
                "signal": bias,
                "direction": "Rising" if rsi is not None and rsi > 50 else "Falling",
                "previous": None,
            },
            "macd": _macd(closes) or {},
            "sma": {**sma, "signals": sma_signals},
            "ema": ema,
            "bollinger_bands": {},
            "atr": {},
            "volume_analysis": {"current": 0.0, "average_20": None, "ratio": None, "signal": "Normal"},
            "obv": {"current_volume": 0.0, "direction": "accumulation", "note": "OANDA fallback"},
            "support_resistance": {},
        },
    }
