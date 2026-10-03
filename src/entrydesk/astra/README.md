# Astra pure calculation subset

Source: https://github.com/Perryong/astra-quant-agent.
Pinned commit: `78c0e4aa768511e888c392aa27de357b02aaf0f4`.
License: the original AstraQuant license text combines GNU Affero General Public License version 3 with the Commons Clause License Condition v1.0 and an Anti-Scam / Financial Fraud Special Addendum; the complete original text is preserved in `LICENSE`. This is not an unmodified AGPL-only grant.

`calculations.py` contains selected pure functions from
`scripts/factors/okx_quant_factors.py`, their constant dependency closure,
and a relative import of `safe_float`, extracted from
`astra_backend/math_utils.py`. `scoring.py` retains the complete upstream
pure scoring module unchanged after an attribution header.

Modified 2026-10-03: extracted pure subset, removed network/environment imports,
and corrected both RSI zero-loss paths: unchanged prices return 50, an all-gain
window returns 100. Ordinary mixed gain/loss windows preserve upstream arithmetic. RSI divergence
calculates only its trailing 20 oscillator samples from exact 14-difference
windows, eliminating unused quadratic prefix work without changing outputs.
No exchange execution, credentials, council, environment, or autonomous code is included.

This code is not covered by the original market-screener MIT license. Preserve
this attribution and the AGPL license when redistributing the covered code and
provide corresponding source as required by that license.
