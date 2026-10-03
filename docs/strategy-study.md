# Selected strategy and repository study

The Strategy overview at `http://127.0.0.1:8768/#/strategy` explains the implemented policy and current evidence. The user delegated selection and implementation without further design handoffs. We chose one fixed, reproducible trend-breakout baseline so its historical and future behavior can be evaluated without selecting a winner from many backtests.

## Reference findings

| Repository | Revision studied | Useful contribution | Excluded from this integration |
| --- | --- | --- | --- |
| [OpenThomas](https://github.com/PredictionMarketTrader/openthomas/tree/fba4a339c6f116222fdb7aa326f35ed11e9cdec8) | `fba4a339c6f116222fdb7aa326f35ed11e9cdec8` | First-observation journal, deterministic vetoes, chronological evaluation and day-grouped uncertainty | Weather forecasting, LLM confidence, binary-contract probability blending and Kelly, exchange execution |
| [Astra Quant Agent](https://github.com/0xethanq/astra-quant-agent/tree/537d16bad3f8a263b1cff624982ddd4fd2419376) | `537d16bad3f8a263b1cff624982ddd4fd2419376` | Explicit trend/momentum factors, unavailable-input semantics and auditable risk conditions | New full-repository imports, autonomous code modification, model councils, unverified order flow/derivatives, execution adapters |

OpenThomas primarily forecasts binary weather contracts. Its price is a bounded event probability; a stock price is not. We did not transplant binary sizing formulas. Source review also found the NO-side replay probability is complemented twice between `weather/replay.py`, `risk/simulate.py` and `risk/engine.py`; direct reuse would not be a trustworthy baseline. Its improvement gate can pass without enough held-out observations, so this app retains absolute evidence minimums.

Astra's current pure scoring module matches the already-vendored version; the local corrected flat/zero-loss RSI behavior is retained. The full score requires ±45, whereas hourly-only trend and momentum can contribute at most ±40. The previous historical entry path therefore could never trigger. The fix is a separate named candle strategy, not lowering the global Astra threshold or filling missing factors with zeros.

Astra also contains trend pullback, momentum continuation and extreme reversion families, plus staged profit protection. Those are plausible research variants, but their names sometimes overstate their tests: the “squeeze” branch does not check a squeeze, and “liquidity sweep” does not check a swept level. We retained the existing strict cost-aware 2R baseline instead of silently mixing multiple unvalidated strategies. No new upstream executable code is imported.

## Exact implemented policy

`trend-breakout-v2`:

1. At least 60 completed hourly bars. Long close exceeds the preceding 20-bar high; short close falls below the preceding 20-bar low. Latest volume is at least 1.5 times the previous 20-bar median.
2. Wilder ADX(14) is at least 22. Long requires RSI ≥50 and positive MACD histogram; short requires RSI ≤50 and negative histogram. Missing/nonfinite inputs reject the setup. RSI and MACD retain the existing pinned factor definitions.
3. A completed 15-minute candle ending at the hourly signal time must confirm the broken level. Later candles cannot retroactively confirm the signal.
4. Stop distance is the preceding hourly candle's ATR(14). Target solves net reward = 2 × net stop loss after the configured per-side costs: stock 0.05%, crypto 0.15%, commodity 0.10%.
5. Selected actionable research policy is long-only stocks/spot crypto. Short signals and continuous commodity contracts remain research-only; borrow/financing/roll/point-value/session economics are not verified.

Actual entry desk eligibility retains actual quote age ≤120 seconds, spread ≤0.5%, signal age ≤75 minutes, source identity, equity session and provider-error gates. The broader Astra composite remains contextual ranking evidence, not a win probability. No indicator count or score is converted into a fabricated probability.

## Validation

The collector requests up to 60 days of 15-minute history alongside hourly history. Confirmed replay uses their overlap, then an 80/20 chronological split. Each decision receives only the then-available prefixes; next hourly open is the historical entry. Positions cannot straddle the train/holdout boundary. Long-policy metrics are separate from short research; a hypothetical short position cannot consume a long-policy entry slot or certify the long policy.

Replay exits at stop, target, or after 24 bars. Gaps through a stop use the opening price; ambiguous OHLC bars hit the stop first; a known open beyond the target precedes the later intrabar range. Missing trade-path bars reject that result. Incomplete terminal trades are not fabricated closed. Prices are unadjusted public history and costs are assumptions; corporate actions, order-book depth and actual fills are not reconstructed. Quote/spread/session execution guards are not proven by candle replay.

Holdout uncertainty is a deterministic 1,000-replicate moving-block bootstrap of five consecutive observed UTC exit days, with a 95% interval. It is unavailable with fewer than 30 trades or 10 distinct days. This groups nearby outcomes but cannot establish independence across assets or future regimes. The evidence gate requires positive lower bound, at least 30 long holdout closes, positive expectancy, profit factor >1.1 and drawdown ≤20%, plus the correct strategy version and confirmed replay. Drawdown assumes 1% equity risk per sequential trade and is not a real account return.

At least 30 genuine forward paper closes are still required for paper readiness. Historical simulations and the new shadow journal do not satisfy that requirement. Passing code tests establishes implementation behavior; it does not establish profitable trading or production execution readiness.

## Forward observation journal

`collect` automatically stores first observations in `.screener/entrydesk/observations.sqlite3`, including rejected setups. Identity includes symbol, source, asset, strategy version and signal close. The saved record includes observation time, input hash, factors, vetoes and reference levels; repeated collection and revised history do not overwrite it.

Fresh confirmed long setups may accumulate hypothetical outcomes from later completed candles. Entry must be strictly after recording, within two hours, and have a complete path from the signal. First-seen future candles are frozen before simulating, so later revisions cannot rewrite an open entry. Stops/targets/timeouts reuse the historical cost model. Outcomes are `forward_shadow`, never `forward_paper`; there are no broker orders, assumed executable quotes, account balances or trade notifications. The public dashboard shows the latest 50 records; the SQLite journal retains history. Aggregate shadow net-R statistics are outcome summaries, not a portfolio equity curve.

`validate` recalculates saved-history reports without appending observations. `demo` is labelled synthetic and never touches the live journal. Existing GitHub collection runs the same `collect` command when this branch's changes are deployed; a static browser refresh does not fetch or record new market observations.

```sh
uv run python -m entrydesk collect --max-seconds 400
uv run python dashboard/build.py
# Re-evaluate existing saved histories without claiming new forward observations:
uv run python -m entrydesk validate --max-seconds 400
uv run python dashboard/build.py
# Run the local UI, if not already running:
uv run python -m http.server 8768 --bind 127.0.0.1 --directory docs
```

The selected strategy needs no LLM key or exchange trading credentials. The supplementary research API setup remains in [api-setup.md](api-setup.md); those keys do not automatically make delayed research feeds executable.

## Licensing and attribution

OpenThomas is MIT; only architectural ideas are reimplemented here. Astra's existing vendored subset retains its complete original AstraQuant license: AGPL-3.0 subject to Commons Clause and the Anti-Scam / Financial Fraud Addendum. See [Astra provenance](astra-provenance.md) and `src/entrydesk/astra/LICENSE`. Current upstream was studied, not wholesale incorporated or relicensed.

## Verification — 4 October 2026, SGT

Final full suite: **422 tests and 2 subtests passed**; 8 opt-in real-network stress tests deselected. JavaScript syntax and research math checks passed. All 18 configured instruments were collected and replayed with confirmed history. Aggregate long outcomes: 150 training closes and 49 holdout closes, at most six holdout closes per instrument. Every readiness gate remains closed; aggregate counts do not satisfy per-instrument evidence requirements. The journal contains 18 first observations, zero eligible shadow positions and zero fabricated closes. The collector/replay returned partial status for the three explicit continuous-futures economics warnings.

An independent review reproduced mutable-cost and incomplete-training occupancy bugs; regression tests failed before both fixes and passed afterward. Re-review found no remaining important findings. Browser checks covered the real Strategy overview and entry navigation, and a labelled temporary fixture verified closed shadow outcomes and expandable audit details. Existing TradingView iframe compatibility and unavailable research feeds remain separate known limitations, documented in the API setup guide.
