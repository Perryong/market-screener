# Market data reliability implementation plan

> Execution: Superpowers systematic debugging, test-driven fixes and parallel domain investigation; proceed under the user's standing autonomous authorization.

**Goal:** Resolve USD ambiguity, calendar gaps, stale market coverage and unexplained entry fields while preserving trading rules and truthful missing-data gates.

**Architecture:** Keep existing static snapshots and provider adapters. Correct collection failures at source, carry source dates and resource expiry into presentation, and expose deterministic setup checks. Never substitute fabricated quotes or promote historical evidence to live readiness.

**Tech stack:** Python collectors, SQLite cache, vanilla JavaScript, GitHub Actions/Pages; existing free data sources.

## Tasks and ownership
- [x] Root: tests for cache expiry metadata, calendar date-range overlap/invalid dates and stale display states; implement in research.py, research_math.js and research.js.
- [x] Calendar agent: regression tests and fixes in research_sources.py for earnings estimate ranges, wider bounded IPO months, macro cadence metadata; probe official long-read feeds.
- [x] Entry agent: reproduce quote-only failure and weekend cold-cache stock omission; regression tests and fixes in feeds.py/runtime.py; add setup_evidence checks and reference-only net R:R without changing thresholds.
- [x] Pipeline agent: test evidence-derived connection states; fix workflow credential scope and visible collection failure reporting in api_sources.py/dashboard.yml.
- [x] Root: expose USD labels/source provenance, refreshed calendar/news/macro coverage, source expiry, readable entry checks; whitelist setup_evidence in build.py.
- [x] Refresh real feeds, rebuild published snapshots, run full pytest and Node suites, review combined changes, browser-check all requested routes at desktop/mobile widths.
- [ ] Commit/PR/CI/merge, trigger updated collection, verify deployed Pages and report source or credential limitations precisely.

## Review focus
- Missing quote with valid candles must preserve research evidence but veto readiness.
- Calendar estimated date ranges must not become duplicate confirmed reports.
- Monthly/quarterly observation periods must not be mistaken for failed daily refreshes.
- Cached or failed APIs must not remain labelled available merely because a key exists.
- USD conversion must retain original audit units; unknown/stale FX must stay unavailable.

## Acceptance checks
`uv run pytest -q`; `node tests/screener/research_math_check.js`; `node tests/screener/usd_display_check.js`; `node tests/screener/technical_display_check.js`; build idempotence and `git diff --check`. Browser: stock USD incl EUR/GBP examples; earnings upcoming/ranges; IPO monthly coverage; economy dates/cadence; news and reads; entry checklist; breakout and crypto timestamps; API configuration versus observed status.

## Verification evidence
- 480 Python tests, 2 subtests and all Node checks passed; 8 external stress cases excluded by the existing suite configuration.
- Latest full collection: 483 resources OK; BLS release-calendar HTTP 403 and optional SEC identification remain unavailable. 132 dated IPO events, 222 news items, 145 long reads, 30 CoinGecko assets.
- 70 breakout records (41 stocks, 29 crypto) with zero DATA_UNAVAILABLE; 38 inactive revised Yahoo baselines were archived and restarted without historical replay. Local pre-recovery SQLite backup retained.
- 115 headline prices/dates match their sorted unique histories. All 18 entry rows include setup checks; BTC net R:R approximately2 remains blocked. Existing published journal/event history retained across the local refresh.
- Independent review found no trading-math or rebaseline protection blocker. Browser checks passed all11 requested routes at375px and USD stock rows at1440px.
- GitHub hourly trigger delivery remains best effort; unavailable optional credentials and upstream HTTP403 are disclosed rather than fabricated.
