# USD pricing and consistency implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent source and technical fixes; root implements shared USD formatting and research views. Review integration before release.

**Goal:** Display monetary prices in USD, preserve original trading computations, and fix evidenced data inconsistencies.

**Architecture:** A pure USDDisplay module converts display values using existing snapshot FX records. EUR crosses use same-date legs, rates older than seven days or future dates fail closed, USDT uses dated CoinGecko USD quotes (max 24 hours). Raw inputs, portfolio storage and strategy engines stay in native units. Price histories use a constant current display rate, explicitly labelled; returns remain native-price returns. Index points, share counts, percentages and FX pair rates retain correct non-dollar units.

**Tech stack:** Python static generator, vanilla JavaScript, existing Yahoo/CoinGecko data, pytest and Node assertions. No extra provider or API key.

## Tasks
- [x] Root: tested pure USDDisplay converter, precise formatting, dated rate coverage, research monetary displays, consistent CSV USD display columns alongside source fields. Preserve native stored portfolio costs and label source-unit input/filter semantics.
- [x] Source implementer: classify Yahoo financial units and preserve cached records when detailed pass has missing price; tests; no trading algorithm edits.
- [x] Technical implementer: prefer newer valid quote over stale technical headline, fix crypto mover schema, convert USDT monetary displays through injected window.__USD_DISPLAY__; tests; preserve indicator timestamps and engine logic.
- [x] Root: inject converter in both embedded views, update breakout display formatting only, repair published financial units using deterministic normalization, rebuild, tests and browser verification.
- [ ] Independent integration review, CI, release and report evidence/limitations.

**Shared contract:** USDDisplay.create(snapshot, nowSeconds?) returns {rates, convert(amount,currency)}. rates[currency] contains {rate,date,source}. USDDisplay.format(value, compact=false) returns dollar string with small-price precision or 'USD unavailable'. Technical iframe receives window.__USD_DISPLAY__ initialized before existing app scripts. Root owns build.py, research.js/view.py, usd_display.js. Technical implementer owns docs/technical.html. Source implementer owns research_sources.py, research.py and their regression tests.

**Accuracy limits:** These are dated public snapshots, not live executable quotes. Missing or stale conversion is explicit. Original audit JSON retains source units for reproducibility. Provider reports cannot be guaranteed accurate by internal consistency checks alone.

## Verification record
- Pure USD checks cover positive/direct/inverse cross rates, matching dates, stale and future observations, actual provider resource IDs, missing FX, real USDT quote, GBP/pence scaling, sub-cent precision, counts versus monetary per-share units, and immutable inputs.
- Source normalization/fallback regression tests: 17 passing. Technical display tests: 8 passing, including newer quote priority, actual crypto mover schema, USD pivot chart copies, missing rates, structured risk/reward and widget-only Coinbase USD mapping.
- Live read-only Yahoo chart spot-checks matched snapshot AAPL (USD), ASML.AS (EUR), HSBA.L (GBp normalized to GBP). This is a three-symbol spot check, not a claim that all provider records are independently verified.
- All 115 research instruments have matching headline/history price and date, sorted unique history. Original prices, currencies, dates, histories and metrics are unchanged; 1,823 Yahoo financial-unit labels were corrected.
- Shared converter injection is idempotent, escaped and leaves original strategy payloads untouched. Prior portfolio positions retain native stored costs; new USD input converts back to storage units, current-FX P&L limitations are explicit.
- Reviewed fixes: reject stale Yahoo:history resources; recognize EUR/xbrli:shares and USD/shares. Independent reviewer rechecked both successfully.
- Browser verified ASML USD price and USD/share EPS while tax ratios/share counts remain nonmonetary; technical NVDA headline now uses newer $233.95 quote; breakout planned prices use actual USDT/USD rate. Mobile USD screens fit 375px.
- Scope addition from later user request: Strategy tab includes a proposed Astra-inspired 4H trend / 1H breakout / 15m retest strategy with risk and validation gates. This is explicitly inactive research; existing trading engines remain unchanged. No new strategy profitability claim or automated execution.
