# Free API implementation plan

Implement inline under the user's existing continuous-execution authorization.

1. Add tested public adapters in `src/screener/api_sources.py`: Kraken, CoinGecko, BLS, EIA, Alpaca, European XBRL and SEC N-PORT. Normalize dates, units and explicit identity. Reuse bounded verified HTTP transport; keep credentials and response errors private.
2. Integrate adapters into research refresh and a `sources` command. Preserve old instrument history, cache timestamps and missing fields; add optional FRED API support. Test missing configuration, shared budgets and refresh merging.
3. Add API connection status and supplementary observations to the existing UI. Wire GitHub secrets and document local `.env` setup without changing account settings. Test rendering with available, stale and missing data.
4. Run bounded live checks, publish the refreshed local snapshot, rebuild, test the suite and inspect the browser. Review the diff and summarize exactly which credentials remain missing.

Review focus: no secret leakage; no false fresh timestamps; no wrong fund series; no segmented/double-counted XBRL facts; no research quotes promoted into entry eligibility. Providers without credentials are implemented and fixture-tested, not represented as live-verified.
