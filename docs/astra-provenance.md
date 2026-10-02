# Pinned Astra factor provenance

[Astra Quant Agent](https://github.com/Perryong/astra-quant-agent) calculations are imported from commit
`78c0e4aa768511e888c392aa27de357b02aaf0f4`, not a moving branch.
The exact original AGPL-3.0 license is preserved in
`src/entrydesk/astra/LICENSE`. The original market-screener MIT license is retained
for original code; imported Astra code is AGPL and must not be represented as MIT.
The combined distribution must honor the applicable AGPL corresponding-source
requirements. This document does not declare that file separation removes them.

Selected source and dependency closure:

- `scripts/factors/okx_quant_factors.py`: MACD series, causal prefix divergence,
  MACD factors/state, RSI factors/zone, VWAP/VPVR, robust depth, required constants.
- `astra_backend/math_utils.py`: `safe_float` only.
- `scripts/factors/scoring.py`: unchanged pure composite score and thresholds.

The adapter rejects malformed, unfinished (at ingestion's supplied observation
clock), overlapping, nonfinite and boolean OHLCV before permissive upstream
helpers run. Factors use chronological 1 h and actual 15 m observations; missing
15 m data is never substituted with hourly or daily candles. Wilder ATR and ADX
are calculated forward in time; indicators contain no future bars.

Documented corrections and naming:

- Upstream RSI treats zero losses as a ratio of 100, which produces approximately
  99 even for constant prices. Both RSI scalar and divergence series paths now
  yield 50 for a constant window and 100 for a genuinely all-gain window. An
  all-loss window remains 0; insufficient samples remain missing.
- RSI divergence calculates only its last 20 oscillator observations, each
  from its exact 14 differences. Earlier oscillator values are never consumed
  by the detector. This removes quadratic prefix work without changing RSI,
  divergence, momentum or composite outputs; seeded random and short-prefix
  parity checks compare every field against the full-prefix reference.
- Astra's `vwap_24h` output is exposed as `vwap`, with actual interval, bar count,
  elapsed UTC window and an explicit completed-15 m-bar label. Up to 96 bars can
  span multiple equity sessions, so this adapter does not call them 24 hours.
- Flat VPVR range previously produced a zero price. The adapter returns its
  actual VWAP price for this degenerate single-price profile.
- Depth uses Astra's multi-order reliability criterion (at least 3 qualifying
  levels per side). A two-column book without order-count evidence cannot be
  reliable. Wrapper rejects crossed, unsorted, duplicate, nonfinite or malformed
  depth; unreliable imbalance is null, never a neutral observation.
- Derivatives, taker/CVD order flow, options and basis remain explicitly absent.
  No missing tier is filled with fabricated zero,50 or 1 observations.
- Composite score is a fixed upstream evidence score, not a probability or a
  trading-readiness claim. Strict quote geometry requires gross reward/risk>=2;
  downstream candidate logic additionally accounts for costs and validation.

Yahoo uses one request per interval, 8-second request timeouts, hourly history
within 729 days and 15 m history for 5 days; the CLI provides an outer process timeout.
Only already-fetched history metadata is inspected, avoiding an additional info
fetch. Quote time must be actual `regularMarketTime`; missing time gives null
quote. Regular equity periods use the XNYS session calendar (holidays, DST,
early close and final partial hour), while crypto is 24/7. Continuous futures
preserve their Yahoo ticker and remain unverified, market-closed and exploratory
until dated contract identity, roll rules, point value and venue session exist.
No cache timestamp may become quote freshness. No import-time network activity,
orders, private account state or credentials are included.

Verification: `uv run pytest tests/unit/test_entry_factors.py`. The optional
local upstream check executes only pinned pure AST function bodies to compare
MACD/scoring outputs, without importing the upstream environment. Deterministic
checks include bad/incomplete candles, RSI pathologies, missing 15 m/derivatives,
strict geometry, depth reliability, prefix invariance and holiday/early close.
