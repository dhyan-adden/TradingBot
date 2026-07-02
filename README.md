# TradingBot

Agentic paper trading harness for the Indian market, plus a project-local
Zerodha Kite MCP setup for Codex.

## Setup

1. Install local dependencies:

   ```bash
   npm install
   ```

   Python uses the local conda env named `tradingbot`:

   ```bash
   conda activate tradingbot
   python -m pip install -e ".[dev]"
   ```

2. Create a local `.env` from `.env.example` and fill:

   ```bash
   cp .env.example .env
   ```

3. Generate the daily access token.

   If your Zerodha app redirect URL is `http://localhost:8080/login`, use the
   local callback helper:

   ```bash
   npm run auth:zerodha -- --listen
   ```

   Open the printed login URL and complete Zerodha login. The helper captures
   the redirected `request_token`, exchanges it, and updates `.env`.

   Manual fallback:

   ```bash
   npm run auth:zerodha
   ```

   Open the printed login URL, complete Zerodha login, then copy the
   `request_token` from the redirect URL and exchange it:

   ```bash
   npm run auth:zerodha -- <request_token>
   ```

4. Start Codex with the project-only Zerodha MCP:

   ```bash
   ./bin/codex-zerodha
   ```

This does not add Zerodha to `~/.codex/config.toml`. The MCP is injected only by
the local launcher above.

Check whether local env values are present without printing secrets:

```bash
npm run env:status
```

Check the Python scaffold:

```bash
conda activate tradingbot
tradingbot config-check
tradingbot event-smoke --db state/trading.db
python -m pytest
```

Live order placement is disabled unless `ZERODHA_ENABLE_TRADING=true` is set and
the `zerodha_place_order` tool is called with `confirm: true`.

## Paper Harness

The current implementation runs paper-only. YFinance is used first for market
data while the event log, risk checks, and markdown memory loop are tested.
Zerodha remains available for later live-data validation; live order execution
is disabled.

```bash
conda activate tradingbot
tradingbot config-check
tradingbot paper-loop --symbols RELIANCE --iterations 1
tradingbot paper-status
tradingbot memory-regenerate --dry-run
```

Run the complete closed-loop dry-run. This fetches data, generates a signal,
runs risk, updates memory, and creates no paper order:

```bash
tradingbot closed-loop --symbols RELIANCE --once --dry-run --poll-interval-seconds 0
```

Run the complete closed loop with paper auto-orders enabled:

```bash
tradingbot closed-loop --symbols RELIANCE TCS INFY --cycles 10 --poll-interval-seconds 60
```

Run the agent-led closed loop. This checks online news/trends first, then writes
trader and portfolio-manager decisions before signal/risk/paper execution:

```bash
tradingbot agent-loop --symbols RELIANCE --once --dry-run --poll-interval-seconds 0
```

Test only the online research stage:

```bash
tradingbot research-smoke --symbol RELIANCE
```

Open the local dashboard:

```bash
tradingbot dashboard
```

Then visit `http://127.0.0.1:8765`.

`paper-loop` does not place orders unless `--buy` is passed. For an explicit
manual paper fill:

```bash
tradingbot paper-order RELIANCE BUY 1 1339 --strategy manual_smoke
```
