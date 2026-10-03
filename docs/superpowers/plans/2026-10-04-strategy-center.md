# Strategy Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. User explicitly delegates design and execution decisions; implement inline, then obtain independent review.

**Goal:** A working Strategy overview backed by an explicit usable candle strategy, chronological validation and an immutable forward observation journal.

**Architecture:** Extend entrydesk's pure strategy and validation functions. Add a small SQLite journal; export public summaries through the existing entry snapshot and static builder. No new dependencies, broker execution or LLM calls.

**Tech Stack:** Python, SQLite, existing yfinance/pandas, vanilla JavaScript/HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-10-04-strategy-center-design.md`

## Global Constraints

- Strategy version `trend-breakout-v2`; one fixed policy, no holdout optimization.
- No broker orders, account changes, purchases or model API calls.
- Keep existing free-source scope and all research routes.
- No synthetic forward paper records; shadow outcomes stay distinct.
- Preserve vendored licenses and local RSI fixes.

## Review Focus

- A valid candle setup must not be blocked by an impossible full-factor score.
- Appending future confirmation bars must not change an earlier decision.
- Missing bars and revised history must not invent or overwrite forward outcomes.
- Small/correlated samples must not receive optimistic confidence claims.
- Public snapshots and demo runs must not expose private data or contaminate live state.

### Task 1: Explicit strategy and confirmed replay

Files: modify `src/entrydesk/validation.py`, `signals.py`, `data.py`; tests in `tests/unit/test_entry_strategy.py` and existing entry signal tests.
Interfaces: `pattern(bars, factors=None)`; `confirmation(bars, bars_15m, side)`; `backtest(bars, asset_class, bars_15m=None)`; `grouped_expectancy(trades)`; `STRATEGY_ID`.
- [ ] Add failing tests: score 35 can qualify with ADX=25/RSI=60/hist>0; score 90 with missing predicates cannot. Future 15m close cannot confirm historical signal. Prefix appending preserves completed trades. Historical split cannot consume holdout.
- [ ] Implement fixed predicates, as-of confirmation and optional confirmed replay, preserve explicitly exploratory hourly-only mode.
- [ ] Add failing tests for deterministic bootstrap with <30 trades/<10 days unavailable and constant positive/negative samples.
- [ ] Implement five-day moving-block bootstrap, 1000 replicates, 95% interval; require version and uncertainty evidence at readiness gate. Increase public 15m collection window to 60d.
- [ ] Run entry test suite and commit.

### Task 2: Immutable observation journal and collection

Files: create `src/entrydesk/journal.py`; modify entry CLI; tests `tests/unit/test_entry_journal.py`.
Interfaces: `Journal(path)`, `observe(bundle, candidate, observed_at)`, `resolve(bundle, observed_at)`, `summary()`, `close()`; export `payload['journal']` and strategy metadata. SQLite primary key identifies source/symbol/strategy/signal close. Observation payload immutable; outcome resolves at most once.
- [ ] Add failing tests for idempotency, changed-history immutability, restart, strictly post-observation entry, stale/future/gapped bars, expiry and no terminal forced close.
- [ ] Implement append-only observations and separately persisted forward-shadow outcomes. Reuse conservative simulation, no new network calls.
- [ ] Wire collect only to journal; validate and demo cannot generate new forward observations. Replay confirmed histories via subprocess with remaining deadline. Export sanitized recent observations and counts.
- [ ] Run journal/CLI tests and commit.

### Task 3: Strategy UI and study documentation

Files: modify `research_view.py`, `research.js`, `dashboard/build.py`, README and Astra provenance; create `docs/strategy-study.md`; builder tests.
- [ ] Add failing builder tests for Strategy route and safe public journal embedding.
- [ ] Implement Strategy overview, exact rules, source comparison, validation and shadow journal tables, entry link and unavailable states; keep score as context.
- [ ] Document repository revisions, transfer decisions, risk gates, local commands and source limitations; correct license shorthand.
- [ ] Run JavaScript syntax/math checks and builder suite; commit.

### Task 4: Live verification and independent review

- [ ] Run full test suite, bounded live collection and saved-history replay; inspect counts and blockers without tuning.
- [ ] Rebuild combined application. Browser-check strategy, entry, crypto and API coverage; capture screenshot; remove only our temporary fixture page.
- [ ] Dispatch fresh-context reviewer with spec/plan and commit range; fix important findings with regression tests.
- [ ] Rerun affected checks and full suite after corrections. Update ledger with measured results and final limitations. Keep existing draft PR branch and local app available.

## Execution ledger

- Design: selected explicit available-data strategy plus OpenThomas evidence architecture. User requested autonomous decisions; no design confirmation required.

- Task 1: RED 6 new strategy tests (including actual indicator arithmetic), then GREEN 45 entry tests. Legacy mocked factor fixtures now include explicit direction inputs; full-factor score remains unchanged. Confirmed replay uses overlapping history and no future quarter.

- Task 2: RED immutable/restart/temporal/gap journal tests and CLI confirmation/demo tests, then GREEN 52 entry tests. First-seen forward candles are frozen separately so provider revisions cannot rewrite an open shadow entry. Aggregate shadow outcome statistics omit a fictitious portfolio equity curve.
