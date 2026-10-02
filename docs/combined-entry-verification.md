# Combined desk verification — 2026-10-03 SGT

The implementation combines market-analysis-screener's research/markets/news and
breakout desk with market-screener's original Desk Tape/MCP functionality. The
new Entry desk includes pinned Astra pure factors and strict entry evidence gates.
Branch: `codex/combined-entry-desk`; upstream base `5b02cfe`.

## Verified software

- Full suite: **383 passed, 8 stress tests deselected, 2 subtests passed**.
- Original collector selftest, native JavaScript syntax and research/portfolio math checks pass.
- Wheel/source distribution builds; wheel includes browser assets and imported
  Astra license/README, and contains no private cache or SQLite state.
- Browser checks: restored research, market and news pages, original technical
  iframe, entry asset filters/details, and mobile 390×844 layout with horizontal
  table scrolling. No page-level horizontal overflow in the checked mobile view.
- Independent reviews reproduced and fixed provider boolean coercion, wrong
  intervals, malformed cache/quote containers, duplicate/future paper records,
  inconsistent risk units, known-opening-gap fills, and tooltip injection.
- Technical iframe cannot access parent portfolio storage; dynamic links accept
  HTTP(S) only, and source/chart popups still work. Private histories and journals
  remain under ignored `.screener`; only normalized snapshots are published.

## Recorded public observations

All 18 instruments supplied completed 1-hour and 15-minute histories from Yahoo.
Quote observation times are provider times, never cache times. Bid/ask was absent
for all instruments. TSM/INTC/KLAC lacked an actual quote price/time pair. Continuous
futures supplied prices but unverified contract/session/point-value/roll economics.
The public snapshot is explicitly **partial**, with six source warnings.

| Symbol | Asset | Hourly bars | 15m bars | Quote price/time |
|---|---|---:|---:|---|
| AMAT | stocks | 3471 | 129 | observed |
| AMD | stocks | 3471 | 129 | observed |
| ARM | stocks | 3471 | 129 | observed |
| ASML | stocks | 3471 | 129 | observed |
| AVGO | stocks | 3471 | 129 | observed |
| BTC-USD | crypto | 17463 | 463 | observed |
| CL=F | commodities | 11296 | 431 | observed |
| ETH-USD | crypto | 17460 | 463 | observed |
| GC=F | commodities | 11434 | 431 | observed |
| INTC | stocks | 3471 | 129 | missing |
| KLAC | stocks | 3471 | 129 | missing |
| LRCX | stocks | 3471 | 129 | observed |
| MU | stocks | 3471 | 129 | observed |
| NVDA | stocks | 3471 | 129 | observed |
| QCOM | stocks | 3471 | 129 | observed |
| SI=F | commodities | 11433 | 431 | observed |
| SPY | stocks | 3470 | 129 | observed |
| TSM | stocks | 3470 | 129 | missing |

Historical validation on these recorded histories produced **0 train trades,
0 holdout trades, 0 forward-paper closes, and 0 ready instruments**. Hourly-only
validation has no 15-minute volume-profile/confirmation replay: its available
Astra trend and momentum contributions are capped at 15+25=40, below the unchanged
45-point recommendation threshold. Thus zero historical trades is structurally
expected for this incomplete factor coverage; it is neither proof of a trading
edge nor a meaningful negative estimate of the full strategy's profitability.
The report explicitly vetoes readiness for unreplayed 15-minute rules.

## Production trading remains unverified

Passing software tests establishes checked behavior, not profitable or safe
market entries. This build has **no order path and no automatic paper writer**.
It cannot compress real elapsed forward testing into a backtest. Before approving
actual entries, the full rules need matching historical 15m evidence, a genuinely
untouched qualifying holdout (at least 30 closes and the documented metrics),
at least 30 audited forward-paper closes, fresh quote/spread evidence, and valid
instrument economics. Stock/spot-crypto shorts remain blocked on unverified
borrowing/financing; continuous futures remain blocked on contract economics.
The modeled flat costs and trade-close drawdown are research assumptions.

No score threshold was lowered or fitted to produce a passing result. Missing
order flow, derivatives, depth, options and basis remain unavailable. Scores are
heuristics, not probabilities. The source snapshot is not a streaming execution
feed and does not provide scalping latency.

## Integration rulings

- Continue without process confirmations as previously authorized; preserve a
  reviewable feature branch/draft PR. Incorrect scope would require reversible rework.
- Combine screening and research only; live execution would require a separate
  authorized subsystem with its own tested data/risk controls.
- Use `stocks`, `crypto`, `commodities` consistently between collectors, algorithms
  and UI; schema drift would cause false blocks or mismatched costs.
- Keep completed-close reference levels explicitly non-executable. They cannot
  substitute for actual quote freshness or a verified spread.
- Preserve exact Astra license/attribution and its applicable addenda, and remove
  misleading whole-project MIT labeling; see [provenance](astra-provenance.md).
- Preserve indicator outputs when optimizing. RSI divergence now avoids unused
  prefixes with exact parity; seeded EMA values and holdout rules were not approximated.
- New reviewer creation hit the session agent-thread limit. Independent reviewers
  were reused across tasks rather than self-approving their own implementation;
  this sacrifices some context isolation. No important known finding remains open
  after final scoped review approved the fixes.

## Reproduce

```sh
uv sync --frozen
uv run pytest -q
uv run python dashboard/collect.py --selftest
node tests/screener/research_math_check.js
uv run python -m entrydesk collect --max-seconds 400
uv run python -m entrydesk validate --max-seconds 400
uv run python dashboard/build.py
uv run python -m http.server 8767 --bind 127.0.0.1 --directory docs
```

Live/recorded commands deliberately exit 1 on partial source coverage while
atomically publishing explicit failures. The deterministic synthetic demo is
separate: `uv run python -m entrydesk demo --output /tmp/demo-entries.json`.

Public JSON and embedded snapshots use compact JSON serialization without dropping
values or history. The complete five-year research dataset is still large
(~22 MiB JSON/~24 MiB combined HTML); lazy per-instrument loading is deferred
until first-load performance warrants the additional publication/routing code.
