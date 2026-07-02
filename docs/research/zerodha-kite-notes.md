# Zerodha Kite Notes

## Auth

Kite Connect uses an API key, API secret, a short-lived `request_token`, and a
daily `access_token`. The local helper exchanges `request_token` into
`ZERODHA_ACCESS_TOKEN` and stores it in `.env`. Codex must not read that file.

The access token expires daily. The current repo uses a local callback helper
for the daily login flow.

## Data Used in V1

- Instrument master for symbol/token lookup.
- Historical daily candles for signal generation.
- LTP/quote endpoints for mark-to-market.
- Holdings/positions only for manual diagnostics, not paper state truth.

## Execution Boundary

Zerodha has no sandbox suitable for the paper loop. The v1 broker is therefore
local and simulated. No real order should be sent to Zerodha from the Python
package in Day 1.

## Operational Notes

- Do not log credentials or full environment dumps.
- Use explicit API version headers.
- Keep request failures structured so data quality gates can reject stale or
  missing market data.
- Live order placement, if ever added, must be behind separate config, review,
  and compliance gates.

Sources:

- Kite Connect docs: https://kite.trade/docs/connect/v3/
- Kite user/session docs: https://kite.trade/docs/connect/v3/user/
- Kite historical candles docs: https://kite.trade/docs/connect/v3/historical/
- Zerodha API FAQ: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs
