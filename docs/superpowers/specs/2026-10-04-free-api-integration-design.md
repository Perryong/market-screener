# Free API integrations

The user authorized the source mix reviewed against Noorult and asked for any missing credentials. Earlier authorization explicitly permits completing work without confirmation. Extend the existing collectors on `codex/combined-entry-desk`; preserve the combined app and never submit orders.

Use the existing bounded cache for public research. Add Kraken market observations, CoinGecko overview, EIA energy history, direct BLS observations, European XBRL filings/facts, SEC N-PORT fund holdings and Alpaca IEX observations. Existing Yahoo, SEC company facts, FRED, Nasdaq calendars and RSS remain. FRED accepts an optional API key with its existing public CSV fallback. Credentials are environment-only, optional providers report missing configuration, and source failures preserve original timestamps. No raw errors or secrets enter HTML, JSON or logs.

European companies require an explicit ticker-to-LEI mapping; never match a filing by fuzzy company name. Fund holdings require the SEC series ID as well as registrant CIK; never use another series' holdings. Parse only unsegmented European facts, retaining period, currency, concept and filing provenance. N-PORT percentages are fractions in the app, with unmapped holdings retained for coverage rather than silently renormalized.

Add a sources refresh command that updates supplemental data without recollecting all Yahoo history, and configuration/status in Data coverage. Display crypto observations on Crypto markets and official energy/jobs series on Economy. Refresh and workflow use the same paths. Keep secrets in an ignored local `.env`, loaded explicitly by the documented `uv run --env-file .env` command. No account creation, purchases, or invented contact email.

TradingView is a display service, not an algorithm data API. Its previously identified iframe issue is reported separately; this change does not remove isolation. Nasdaq web access remains best-effort, not a promised free licensed market feed. No free commodity execution feed is assumed.

Validation: offline fixture tests for real response schemas, nonfinite/future observations, credential omission and leakage, XBRL dimensions, N-PORT series identity, cache failure recovery and end-to-end snapshot/UI wiring; bounded live checks of credential-free endpoints; full existing test suite and browser inspection. Missing credentials prevent live verification of those providers and must be listed honestly.
