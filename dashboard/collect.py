#!/usr/bin/env python3
"""Collect a full-universe analysis snapshot into docs/data.json.

Runs the MCP server's own tool functions in-process (no MCP client needed) and
merges the result over the previous snapshot: any section whose upstream failed
keeps its last-good value and is flagged stale, so one flaky provider never
blanks the dashboard.

  python dashboard/collect.py                # tier picked from UTC hour
  python dashboard/collect.py --tier daily   # force the Yahoo/backtest tier
  python dashboard/collect.py --selftest     # merge-logic check, no network
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

OUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"

# venues are tried in order: TradingView drops symbols from a venue without warning
UNIVERSE = [
    {"key": "BTCUSDT", "label": "Bitcoin",        "group": "Crypto",      "venues": ["KUCOIN", "BINANCE"], "yahoo": "BTC-USD", "cat": "crypto"},
    {"key": "ETHUSDT", "label": "Ethereum",       "group": "Crypto",      "venues": ["KUCOIN", "BINANCE"], "yahoo": "ETH-USD", "cat": "crypto"},
    {"key": "XAUUSD",  "label": "Gold",           "group": "Commodities", "venues": ["OANDA", "TVC"],      "yahoo": "GC=F",    "cat": "stocks"},
    {"key": "USOIL",   "label": "WTI Crude",      "group": "Commodities", "venues": ["TVC", "OANDA"],      "yahoo": "CL=F",    "cat": "stocks"},
    {"key": "SPY",     "label": "SPDR S&P 500",   "group": "Index ETFs",  "venues": ["AMEX"],              "yahoo": "SPY",     "cat": "stocks"},
    {"key": "VOO",     "label": "Vanguard S&P500","group": "Index ETFs",  "venues": ["AMEX"],              "yahoo": "VOO",     "cat": "stocks"},
    {"key": "NVDA",    "label": "NVIDIA",         "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "NVDA",    "cat": "stocks"},
    {"key": "AMD",     "label": "AMD",            "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "AMD",     "cat": "stocks"},
    {"key": "AVGO",    "label": "Broadcom",       "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "AVGO",    "cat": "stocks"},
    {"key": "ASML",    "label": "ASML",           "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "ASML",    "cat": "stocks"},
    {"key": "TSM",     "label": "TSMC",           "group": "Semis",       "venues": ["NYSE"],              "yahoo": "TSM",     "cat": "stocks"},
    {"key": "MU",      "label": "Micron",         "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "MU",      "cat": "stocks"},
    {"key": "INTC",    "label": "Intel",          "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "INTC",    "cat": "stocks"},
    {"key": "QCOM",    "label": "Qualcomm",       "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "QCOM",    "cat": "stocks"},
    {"key": "AMAT",    "label": "Applied Materials","group": "Semis",     "venues": ["NASDAQ"],            "yahoo": "AMAT",    "cat": "stocks"},
    {"key": "LRCX",    "label": "Lam Research",   "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "LRCX",    "cat": "stocks"},
    {"key": "KLAC",    "label": "KLA Corp",       "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "KLAC",    "cat": "stocks"},
    {"key": "ARM",     "label": "Arm Holdings",   "group": "Semis",       "venues": ["NASDAQ"],            "yahoo": "ARM",     "cat": "stocks"},
]

# TradingView throttles by call volume per IP: a burst of ~40 TA calls goes
# through, then the scanner starts answering with empty bodies. Multi-timeframe
# costs 5 calls per symbol and the rule summary adds a 6th, so running both
# across 18 symbols is what tips a run over. They run on the six headline
# instruments hourly and across the whole list on the daily tier; the per-symbol
# snapshot and volume read (1 call each) cover everything else every hour.
MACRO = ["BTCUSDT", "ETHUSDT", "XAUUSD", "USOIL", "SPY", "VOO"]

# Yahoo-backed tools only run on the daily tier (GitHub runner IPs get 429'd
# often enough that hourly retries would just burn minutes for nothing).
DAILY_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XAUUSD", "USOIL", "SPY", "VOO", "NVDA"]

# Marketaux budget is 90 calls/day and each analysed symbol costs 1-2. Two
# symbols per run rotates the whole universe through in ~9h at ~48 calls/day.
NEWS_PER_RUN = 2

# Tools served by tradingview_ta (the endpoint the breaker guards). The screener,
# futures and Yahoo tools use different upstreams and keep running regardless.
TA_TOOLS = {
    "coin_analysis", "multi_timeframe_analysis", "volume_confirmation_analysis",
    "multi_agent_analysis", "top_gainers", "top_losers", "bollinger_scan",
    "rating_filter", "smart_volume_scanner", "volume_breakout_scanner",
    "consecutive_candles_scan", "advanced_candle_pattern",
}

# Hard wall-clock cap. A TradingView scanner outage puts every call into 3
# retries plus a failure cooldown, which can stretch a run past its own hourly
# schedule. Once the budget is gone the remaining sections are skipped, and
# merge() keeps their last-good values — a stale panel beats overlapping runs.
BUDGET_S = int(os.environ.get("COLLECT_BUDGET_S", "1500"))

# tradingview_ta and the screener endpoint fail independently — one can be dead
# for an hour while the other serves fine. Every failed TA call costs ~4.5s of
# retries plus a 15s shared cooldown, so 70+ of them outlive the hourly schedule.
# After this many consecutive failures the TA family is declared down and the
# rest of its calls are skipped, which keeps the run short and lets merge() hold
# the last good values.
TA_BREAKER = int(os.environ.get("COLLECT_TA_BREAKER", "6"))
# The breaker opens, it does not latch: throttling is usually partial, so after
# this long one call is let through as a probe and a success reopens the family.
TA_PROBE_S = int(os.environ.get("COLLECT_TA_PROBE_S", "90"))
# ...or after this many skipped calls, whichever lands first. Skipping is cheap,
# so a throttled run can finish well inside TA_PROBE_S and never probe at all —
# which turns a partial throttle into a total blackout for the whole run.
TA_PROBE_SKIPS = int(os.environ.get("COLLECT_TA_PROBE_SKIPS", "10"))
# Each failed probe doubles the wait before the next one (capped). Probing on a
# fixed interval through a sustained block spends the whole run on retries —
# 700s in testing — while backing off recovers from a brief blip just as fast.
TA_PROBE_BACKOFF_MAX = 4

# market-pivot-watch publishes its own completed-4H pivot analysis as JSON on a
# separate schedule. Consume that instead of reimplementing the breakout/retest/
# invalidation rules here — two copies of a strategy drift, and its repo is the
# one that owns them.
PIVOT_FEED = os.environ.get(
    "PIVOT_WATCH_URL",
    "https://raw.githubusercontent.com/Perryong/market-pivot-watch-/main/output/latest.json",
)

_errors: list[str] = []
_started = time.time()
_ta_fails = 0
_ta_down = False
_ta_down_at = 0.0
_ta_skipped = 0
_ta_probes = 0


def fetch_pivot_watch() -> dict:
    """Pull the published pivot-watch report. Raises on anything unusable."""
    # requests (already a dependency) ships certifi; stdlib urllib uses the
    # system trust store, which a uv-managed interpreter does not have.
    import requests
    resp = requests.get(PIVOT_FEED, timeout=20, headers={"User-Agent": "desk-tape-dashboard"})
    resp.raise_for_status()
    report = resp.json()
    if not report.get("markets"):
        raise ValueError(f"pivot feed has no markets: {str(report)[:120]}")
    report["feed_url"] = PIVOT_FEED
    return report


def _tool(name):
    from tradingview_mcp import server
    t = getattr(server, name)
    return getattr(t, "fn", t)


def _call(name, *a, **k):
    fn = _tool(name)
    r = fn(*a, **k)
    return asyncio.run(r) if hasattr(r, "__await__") else r


def _label(name) -> str:
    return getattr(name, "__name__", str(name))


def _is_err(v) -> bool:
    return isinstance(v, dict) and bool(v.get("error"))


def over_budget() -> bool:
    return time.time() - _started > BUDGET_S


def _skipped(why: str) -> dict:
    return {"ok": False, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "took_s": 0.0, "data": {"error": f"skipped: {why}"}}


def section(name, *a, **k) -> dict:
    """One tool call — an MCP tool name, or any callable — as a dashboard section."""
    global _ta_fails, _ta_down, _ta_down_at, _ta_skipped, _ta_probes
    t0 = time.time()
    if over_budget():
        return _skipped(f"{BUDGET_S}s collection budget spent")
    if _ta_down and name in TA_TOOLS:
        factor = 2 ** min(_ta_probes, TA_PROBE_BACKOFF_MAX)
        if time.time() - _ta_down_at < TA_PROBE_S * factor and _ta_skipped < TA_PROBE_SKIPS * factor:
            _ta_skipped += 1
            return _skipped(f"tradingview_ta throttled ({TA_BREAKER} consecutive failures)")
        _ta_down, _ta_fails, _ta_skipped = False, 0, 0  # this call is the probe
        _ta_probes += 1
    try:
        data = name(*a, **k) if callable(name) else _call(name, *a, **k)
        ok = not _is_err(data)
        if not ok:
            _errors.append(f"{_label(name)}{a}: {json.dumps(data.get('error'), default=str)[:160]}")
    except Exception as e:  # a tool raising is a bug, but it must not kill the run
        data, ok = {"error": f"{type(e).__name__}: {e}"}, False
        _errors.append(f"{_label(name)}{a}: {type(e).__name__}: {e}")
    if name in TA_TOOLS:
        if ok:
            _ta_fails, _ta_probes = 0, 0
        else:
            _ta_fails += 1
        if _ta_fails >= TA_BREAKER and not _ta_down:
            _ta_down, _ta_down_at = True, time.time()
            _errors.append(f"circuit breaker: tradingview_ta declared down after {TA_BREAKER} failures")
            print(f"  ! tradingview_ta throttled after {TA_BREAKER} failures — "
                  f"pausing its calls, probing again in {TA_PROBE_S}s", flush=True)
    return {
        "ok": ok,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "took_s": round(time.time() - t0, 2),
        "data": data,
    }


def first_venue(name, sym: dict, *a, **k) -> dict:
    """Try each venue in turn; return the first section that came back ok."""
    last = None
    for venue in sym["venues"]:
        last = section(name, sym["key"], venue, *a, **k)
        if last["ok"]:
            last["venue"] = venue
            return last
        if _ta_down or over_budget():
            break
    last["venue"] = sym["venues"][-1]
    return last


def merge(old: dict, new: dict) -> dict:
    """Section-level merge: a failed new section falls back to the last good one.

    Keeps the dashboard populated through upstream outages instead of showing a
    wall of errors, and marks what it is showing as stale so nobody reads a
    3-hour-old price as live.
    """
    if not isinstance(old, dict):
        return new
    out = dict(new)
    for k, nv in new.items():
        ov = old.get(k)
        if not isinstance(nv, dict) or not isinstance(ov, dict):
            continue
        if "ok" in nv:  # a leaf section
            if not nv["ok"] and ov.get("ok"):
                out[k] = {**ov, "stale": True, "last_error": nv["data"].get("error"),
                          "last_try": nv["as_of"]}
        else:
            out[k] = merge(ov, nv)
    return out


def g_rows(sec_: dict | None) -> list[dict]:
    """The rows of a screener-style section, or [] if it failed."""
    if not sec_ or not sec_.get("ok"):
        return []
    return (sec_.get("data") or {}).get("rows") or []


def collect(tier: str) -> dict:
    hour = datetime.now(timezone.utc).hour
    daily = tier == "daily"
    # Wider spacing than the server's interactive default: a batch collector that
    # keeps the 0.5s default gets throttled to empty bodies about 40 calls in.
    os.environ.setdefault("TRADINGVIEW_MCP_MIN_INTERVAL_S", "2.0")

    symbols: dict[str, dict] = {}
    for i, sym in enumerate(UNIVERSE):
        print(f"[{i+1}/{len(UNIVERSE)}] {sym['key']}"
              + (" (budget spent, skipping)" if over_budget() else ""), flush=True)
        sec = {
            "analysis": first_venue("coin_analysis", sym, "1D"),
            "volume":   first_venue("volume_confirmation_analysis", sym, "1D"),
        }
        if sym["key"] in MACRO or daily:
            sec["mtf"] = first_venue("multi_timeframe_analysis", sym)
            sec["agents"] = first_venue("multi_agent_analysis", sym, "1D")
        # news rotates: (hour + index) picks NEWS_PER_RUN symbols each run
        if (i - hour) % (len(UNIVERSE) // NEWS_PER_RUN) == 0:
            sec["sentiment"] = section("market_sentiment", sym["key"], sym["cat"], 20)
        if daily and sym["key"] in DAILY_SYMBOLS:
            sec["strategies"] = section("compare_strategies", sym["yahoo"], "1y")
            sec["walk_forward"] = section("walk_forward_backtest_strategy", sym["yahoo"], "supertrend", "2y")
            sec["smart_money"] = section("smart_money_analysis", sym["key"], sym["venues"][0], "6mo")
            sec["yahoo"] = section("yahoo_price", sym["yahoo"])
        symbols[sym["key"]] = {"label": sym["label"], "group": sym["group"], "sections": sec}

    print("market-wide scans", flush=True)
    market = {
        "snapshot":       section("market_snapshot"),
        "btc_pulse":      section("bitcoin_market_pulse"),
        "gainers":        section("top_gainers", "KUCOIN", "4h", 10),
        "losers":         section("top_losers", "KUCOIN", "4h", 10),
        "squeeze":        section("bollinger_scan", "KUCOIN", "4h", 0.04, 12),
        "smart_volume":   section("smart_volume_scanner", "KUCOIN", 2.0, 2.0, "any", 12),
        "futures":        section("futures_market_overview", "all", "us", 20),
        "futures_movers": section("futures_top_movers", "gainers", "us", 12),
        "energy":         section("futures_category_snapshot", "energy"),
        "metals":         section("futures_category_snapshot", "metals"),
        "watchlist":      section("futures_watchlist"),
        "us_screener":    section("stock_screener", "america", "common", 25),
        "equity_quotes":  section("stock_prices", ",".join(
            f"{x['venues'][0]}:{x['key']}" for x in UNIVERSE
            if x["group"] in ("Semis", "Index ETFs"))),
        "news":           section("financial_news", None, "stocks", 12),
    }
    if daily:
        # each of these sweeps the exchange universe in ~6 batched TA calls
        market["strong_rated"] = section("rating_filter", "KUCOIN", "1h", 2, 12)
        market["vol_breakout"] = section("volume_breakout_scanner", "KUCOIN", "1h", 2.0, 3.0, 12)
        market["streaks"] = section("consecutive_candles_scan", "KUCOIN", "1h", "bullish", 3, 2.0, 12)
        market["candle_pattern"] = section("advanced_candle_pattern", "KUCOIN", "1h", 3, 10.0, 12)
        market["nvda_hours"] = section("stock_extended_hours", "NVDA")
        market["nvda_options"] = section("stock_options_unusual_activity", "NVDA", 10, 100, 4)
        market["nvda_chain"] = section("stock_options_chain", "NVDA")

    # tradingview_ta and the screener are separate upstreams: when the first is
    # throttled the second still answers, so a symbol with no analysis can still
    # show a real last price instead of an error string.
    quotes = {r.get("symbol"): r for r in (g_rows(market.get("equity_quotes")) + g_rows(market.get("us_screener")))}
    for key, entry in symbols.items():
        if entry["sections"]["analysis"].get("ok") or entry["sections"]["analysis"].get("stale"):
            continue
        q = quotes.get(key)
        if q:
            entry["sections"]["quote"] = {
                "ok": True,
                "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "took_s": 0.0,
                "data": {"price": q.get("price"), "change_percent": q.get("change_percent"),
                         "ticker": q.get("ticker"), "source": "tradingview screener"},
            }

    strategy = {"pivot_watch": section(fetch_pivot_watch)}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tier": tier,
        "symbols": symbols,
        "market": market,
        "strategy": strategy,
        "meta": {
            "universe": len(UNIVERSE),
            "errors": _errors,
            "news_enabled": bool(os.environ.get("MARKETAUX_API_TOKEN")),
            "budget_s": BUDGET_S,
            "budget_spent": over_budget(),
            "ta_upstream_throttled": _ta_down,
        },
    }


def selftest() -> None:
    good = {"ok": True, "as_of": "t1", "data": {"price": 1}}
    bad = {"ok": False, "as_of": "t2", "data": {"error": "boom"}}
    old = {"symbols": {"BTC": {"sections": {"a": good, "b": good}}}}
    new = {"symbols": {"BTC": {"sections": {"a": bad, "b": {"ok": True, "as_of": "t2", "data": {"price": 2}}}}}}
    m = merge(old, new)
    a = m["symbols"]["BTC"]["sections"]["a"]
    assert a["data"]["price"] == 1 and a["stale"] and a["last_error"] == "boom", a
    assert m["symbols"]["BTC"]["sections"]["b"]["data"]["price"] == 2, "fresh value must win"
    assert "stale" not in m["symbols"]["BTC"]["sections"]["b"]
    # a section with no previous value stays failed rather than vanishing
    assert merge({}, {"x": bad})["x"]["ok"] is False
    print("selftest ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["hourly", "daily"], default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0

    tier = args.tier or ("daily" if datetime.now(timezone.utc).hour == 0 else "hourly")
    t0 = time.time()
    snap = collect(tier)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    snap = merge(old, snap)
    snap["build_seconds"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, indent=1, default=str))
    secs = [s["sections"]["analysis"] for s in snap["symbols"].values()]
    fresh = sum(1 for a in secs if a["ok"] and not a.get("stale"))
    stale = sum(1 for a in secs if a.get("stale"))
    quotes = sum(1 for s in snap["symbols"].values() if s["sections"].get("quote"))
    print(f"wrote {OUT} tier={tier} {fresh}/{len(UNIVERSE)} fresh, {stale} stale, "
          f"{quotes} quote-only, {len(_errors)} errors, {snap['build_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
