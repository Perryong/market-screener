# Free-source API setup

All integrations collect read-only research. They do not place orders or establish that an entry strategy is production-ready. Credentials are read by Python, never by the static website. An existing deployment will not acquire new credentials until the workflow changes are deployed and repository secrets are configured.

## Local setup

Copy `.env.example` to `.env` only if `.env` does not already exist. The repository ignores `.env`. Enter credentials in that local file, not in chat or in `research.json`. Run from the repository root:

```sh
uv run --env-file .env python -m screener sources --state-dir .screener/live --out .screener/public
```

`sources` refreshes the supplemental APIs and retains saved research, including its original timestamp. For the full research universe, use `research` instead. Both report source failures in Data coverage and keep last successful data with its original fetch timestamp. `--force` retries failed sources; do not use it in a polling loop.

Rebuild the combined app after collection:

```sh
cp .screener/public/research.json docs/research.json
uv run python dashboard/build.py
uv run python -m http.server 8768 --bind 127.0.0.1 --directory docs
```

The home page is http://127.0.0.1:8768/#/home and the connection dashboard is http://127.0.0.1:8768/#/coverage . A static page refresh does not recollect API data; run the collector again.

## What you need to supply

| Provider | Variables | Registration / details |
| --- | --- | --- |
| SEC EDGAR | `SEC_USER_AGENT` | A truthful contact name and email, e.g. `Market Screener Your Name your@email.com`. This is sent to SEC as identification; no API key is required. [Access rules](https://www.sec.gov/about/developer-resources). |
| Alpaca | `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Paper account API credentials from your [Alpaca dashboard](https://app.alpaca.markets/). The added research collector requests IEX only, not paid SIP. |
| CoinGecko | `COINGECKO_DEMO_API_KEY` | [Free Demo plan](https://www.coingecko.com/en/api/pricing); attribution is displayed on Crypto markets. |
| EIA | `EIA_API_KEY` | [Free API key](https://www.eia.gov/opendata/register.php). Enables dated daily WTI/Brent spot series on Economy. |
| FRED | `FRED_API_KEY` (optional) | [API key](https://fred.stlouisfed.org/docs/api/api_key.html). The existing public CSV source remains a fallback. |
| BLS | `BLS_API_KEY` (optional) | [Registration](https://data.bls.gov/registrationEngine/). Without it, use the unregistered v1 API; BLS has lower unregistered quotas. |
| Marketaux | `MARKETAUX_API_TOKEN` (optional) | [Account](https://www.marketaux.com/). Existing technical/news tools use this; RSS headlines continue without it. This provider remains in the technical collector, not the supplemental sources command. |

Kraken public quotes, European XBRL, Yahoo research, the existing Nasdaq IPO calendar and publisher RSS need no secrets. Yahoo access is unofficial and its data terms govern usage; Nasdaq website endpoints are best-effort, not a licensed real-time market feed. Free access does not imply public redistribution rights for every dataset.

For scheduled GitHub collection, add the same variables under repository **Settings → Secrets and variables → Actions**. The workflow references these names. Never commit their values. Repository secrets and local `.env` are separate.

## Coverage and provenance

Supplemental API requests share the full refresh’s remaining request allowance and original deadline. Each supplemental HTTP request consumes one allowance. Legacy collectors count provider operations; internal yfinance HTTP calls and the FRED API-to-CSV fallback are not counted separately. These limits bound collection work, but are not an exact network-call quota for legacy libraries.

- European filings are matched by verified LEI in `research.json` → `xbrl_entities`. The initial mapping is ASML.AS → 724500Y6DUVHQD6OXN27, verified against the XBRL entity API. Add other verified mappings to extend coverage. Unmapped companies keep Yahoo research; no fuzzy matching is used.
- XBRL facts retain original concepts, currency, dates and filing links. Segment facts are omitted, and conflicting duplicates are excluded. The raw facts are not automatically substituted into cross-company valuation ratios.
- SEC N-PORT uses the SEC ticker/class/series map and checks the series inside each filing. It inspects at most 12 recent N-PORT filings per fund. If no matching report is found, coverage reports unavailable rather than using another fund. Missing ticker identifiers are retained as CUSIPs. Portfolio X-Ray can only match securities it knows; derivative/short exposure is not a full risk model.
- Kraken BTC/USD and ETH/USD REST quotes include bid/ask but no quote timestamp; retrieval time is not invented as quote time. They appear on Crypto markets as research observations. Binance strategy history remains separately attributed.
- Alpaca IEX observations appear on Today’s market. Existing breakout and Entry desk algorithms do not consume the supplemental research quotes. The breakout provider remains configurable in `screener.json`; switching to Alpaca there requires `provider: "alpaca"`, `environment: "paper"`, `feed: "iex"` plus the same credentials. IEX volume is not consolidated US volume.
- EIA prices are dated spot observations, not live dated-futures quotes. Commodity entry evidence still needs actual contract, session and executable-price data.
- TradingView remains a display service. Its previously diagnosed sandbox compatibility issue is not fixed by supplying API credentials; iframe isolation is retained.

## Verification

```sh
uv run pytest
node tests/screener/research_math_check.js
node --check src/screener/research.js
```

Offline fixtures cover identity, units, incomplete data, future quote timestamps, request limits, failure redaction and retaining existing research. Providers requiring missing credentials cannot be live-verified until those values are supplied.

Latest local verification (4 October 2026, SGT): 400 tests and 2 subtests passed; 8 opt-in integration tests were deselected. JavaScript syntax and research math checks passed. Browser checks covered the connection dashboard, live Kraken observations, and labelled synthetic Alpaca/CoinGecko rows. Live collection succeeded for Kraken, BLS and ASML XBRL (347 consolidated numeric facts); other credential-gated providers remain unverified live. Existing saved research still contains five stale/unavailable resources, including the Nasdaq IPO calendar, publisher feeds, BLS release calendar and missing SEC configuration. The sources command intentionally returned a nonzero status for these coverage gaps.
