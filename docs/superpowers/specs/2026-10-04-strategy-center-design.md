# Strategy center and forward evidence

The user asks us to study PredictionMarketTrader/openthomas and 0xethanq/astra-quant-agent, select the strategy, implement without human design handoffs while they sleep, and use free sources first. This is an architectural extension of the existing entry desk. Proceed inline under that explicit authorization, with an independent final review. Preserve read-only behavior and all existing research routes. No broker orders, account changes, purchases or model API calls.

## Decision and source study

OpenThomas fba4a339c6f116222fdb7aa326f35ed11e9cdec8 is principally a binary weather forecaster. Adapt its immutable decision journal, chronological evidence, grouped uncertainty estimates and deterministic vetoes. Do not copy weather probabilities, LLM confidence, market-price probability blending or binary Kelly sizing into directional prices. Its NO-side simulation complements already side-relative probability again; direct transplantation would be incorrect.

Astra 537d16bad3f8a263b1cff624982ddd4fd2419376 has the same pure scorer already vendored from 78c0e4aa768511e888c392aa27de357b02aaf0f4 (apart from retained local RSI corrections). Do not refresh or expand the vendored subset. Preserve its complete AGPL/Commons Clause/addendum text and correct shorthand provenance. Its full factor score requires unavailable derivatives/orderflow evidence; the current hourly backtest can score at most 40 but requires 45, so cannot trade. Replace that dependency with explicit predicates from available candles. The broad score remains labelled context, never win probability.

Alternatives considered: copying an autonomous LLM trader adds model costs, opaque recommendations and unsuitable execution assumptions; multiple unvalidated setup families increase selection bias. Select one fixed, versioned trend breakout and expose its actual evidence and limitations.

## Fixed strategy

Version `trend-breakout-v2`: at least 60 completed hourly bars; close above preceding 20-bar high (long) or below preceding 20-bar low (short); volume at least 1.5 times preceding 20-bar median; ADX(14) >=22; positive/negative MACD histogram and RSI >=50/<=50 in the corresponding direction. The most recent completed 15-minute bar at the hourly signal close must share that close time and remain beyond the breakout level. Hourly and 15-minute factors use only data available at the signal time. Missing values reject the setup. No tuning against the holdout. Shorts and continuous commodities remain research-only under existing borrow/contract vetoes.

Stop: one previous-candle Wilder ATR(14); target solves net reward/risk >=2 after configured per-side cost. Historical entry: next hourly open, up to 24 bars; gap stops and ambiguous stop/target bars use conservative fills. Keep the exploratory hourly-only comparison separately labelled. Confirmed validation uses the overlapping 15-minute history, an 80/20 chronological split, no positions crossing the split and explicit confirmation coverage/skips. Request 60 days of public 15-minute history. Quote/session/source and existing forward-paper gates remain in force.

Grouped uncertainty: deterministic 1,000-replicate bootstrap of contiguous five observed exit-day blocks from holdout net-R, 95% interval. Report unavailable below 30 trades or 10 distinct exit days. No probability interpretation; no claim of independent market regimes. Conservative evidence promotion also requires positive lower expectancy bound, existing profit factor/drawdown/sample gates, correct strategy version and confirmed replay. Historical evidence cannot manufacture forward paper records.

## Immutable forward observation journal

SQLite under `.screener/entrydesk/observations.sqlite3`; store each symbol/source/strategy/signal-close observation once, including rejections, observed-at time, data fingerprint, reference entry/stop/target, reasons and factor context. Do not overwrite a first observation when the provider revises history. Subsequent collection may resolve eligible, fresh, confirmed long setups using only later observed candles: enter at the first completed bar whose start is strictly after recording, with at most a two-hour entry window; stop/target/24-bar timeout follows the same fee-aware simulator. Expire unfilled signals; reject gaps/missing coverage instead of inventing fills. These are `forward_shadow` outcomes, not broker fills or `forward_paper` certification. Commodity and short observations remain journaled without hypothetical fills. Export bounded summaries and recent observations, never credentials or local paths. Demo mode never writes the live journal.

## Strategy center

Add Strategy overview route above Entry desk. Show selected strategy and exact predicates, source comparison/attribution, per-asset applicability, live candidate/veto counts, chronological holdout metrics and confidence intervals, and immutable journal progress/outcomes. Explain differences between ranking score, historical simulation, forward shadow outcomes and genuine forward paper validation. Entry desk links to the strategy overview. Missing data shows unavailable, not success. Existing technical/breakout/crypto pages remain available.

## Verification and completion

Failing-then-passing tests for real candle breakout without score>=45; missing/malformed factors; temporal confirmation without lookahead; split boundaries; fee/gap/terminal fills; deterministic grouped bootstrap; immutable journal identity/revisions/repeated runs/restart/future bars/gaps; demo isolation and public snapshot sanitization. Run full suite, bounded live collection, saved-history replay and browser checks with real and labelled fixture data. Review all changes independently. Publish the local updated app and report evidence gaps and any credentials still needed; do not call a strategy production-proven without genuine forward evidence.
