# Combined Entry Desk Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent tasks, with task reviews and final review. User authorized autonomous continuation without confirmations.

**Goal:** Integrate both dashboards and pinned Astra calculation/risk logic into market-screener with tested multi-asset entry evidence.
**Architecture:** Existing MCP stays intact; port screener to src; pure entrydesk modules publish JSON; combined static app retains Desk Tape.
**Tech Stack:** Python >=3.11, current installed dependencies plus the existing screener's yfinance/exchange-calendars; native JS/HTML, pytest/unittest.
**Spec:** docs/superpowers/specs/2026-10-03-combined-entry-desk-design.md

## Constraints / review focus
- No orders, secrets, automatic live readiness or private state publication.
- Invalid/unfinished/stale/duplicate bars must fail closed; test ingestion.
- No future information in indicators/holdouts/fills; prefix-invariance checks.
- Missing derivatives/depth never become neutral observations; provenance test.
- Fees/slippage/gaps/ambiguous exits and futures identity cannot inflate readiness.
- Preserve both previous test suites and dashboards; script escaping and local portfolio storage stay intact.

### Task 1: Port and combined publication
Files: src/screener/*, tests/screener/*, root screener.json/research.json, dashboard/build.py, docs/technical.html, pyproject.toml/uv.lock, workflow, README.
- [ ] Port unchanged modules/tests/config/assets first; run old suite and MCP suite.
- [ ] Build combined docs/index.html from normalized research/strategy and entries snapshots; preserve Desk Tape in technical route, safely embed data and leave no private-cache output. Add Entry desk route with asset/state filters and details, explain readiness vetoes.
- [ ] Workflow retains hourly schedule; cache private screener state, bounded independent collectors and final publication even when provider fails; public outputs only.
- [ ] Tests: rendering escaping, combined routes with no data, no private-state leak. Commit and review.

### Task 2: Pinned Astra factor adapter and public data
Files: src/entrydesk/__init__.py, factors.py, data.py, astra/*, tests/unit/test_entry_factors.py, provenance doc/license.
- [ ] Write failing checks for malformed/incomplete candles, finite/null handling, exact upstream MACD/scoring parity, unavailable derivatives, zero/constant RSI, crossed depth.
- [ ] Vendor selected pure Astra functions and dependencies with pinned source/license. Adapter validates first, fixes observed pathological cases with explicit notes; causal ATR/ADX, interval-correct VWAP, actual15m evidence.
- [ ] Public Yahoo1h/15m collector includes real quote observation timestamp, regular-market sessions via exchange-calendars for equities, continuous-futures limitations, bounded HTTP/data. Expose collect_symbol contract from spec; no import-time network.
- [ ] Run deterministic tests and bounded smoke; commit and review.

### Task 3: Candidate gates and chronological validation
Files: src/entrydesk/signals.py, validation.py, __main__.py, tests/unit/test_entry_signals.py.
- [ ] Write failing tests for bad prices/quotes, missing confirmation, closing market, net RR, next-bar fills, gaps and stop-first ambiguity, holdout readiness/insufficient samples, future-prefix invariance, continuous-futures block.
- [ ] Implement evaluate/backtest contracts in spec with fixed causal rules and cost model; scoring is not a probability. Persist histories privately, atomic public outputs, bounded collection, explicit synthetic demo. CLI collect/validate/demo; existing collect_symbol contract supplied by Task2.
- [ ] Run reproducible validation report over recorded public data; preserve holdout and report failure rather than optimize until pass. Commit and review.

### Task 4: Integration validation and review
- [ ] Full286+54 baseline and new tests, JS checks, collector selftest, deterministic demo build and browser desktop/mobile.
- [ ] Bounded live refresh/backtest all3asset classes; record provider errors, identity limits, holdout and forward-paper gaps.
- [ ] Whole branch independent review, fix important findings with tests and scoped re-review.
- [ ] Commit documentation, push feature branch and draft PR if possible, attach PR, preserve local app. No merge/deploy or orders.
