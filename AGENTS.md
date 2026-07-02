# TradingBot Codex Instructions

This project contains local trading credentials.

Rules for Codex sessions in `/Volumes/D-DRIVE/TradingBot`:

- Never read, print, summarize, grep, cat, sed, or otherwise inspect `.env`.
- Never print environment variable values whose names include `KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `AUTH`, or `CREDENTIAL`.
- Do not run shell snippets that echo or serialize `process.env` or `.env` contents.
- It is allowed to run project scripts that consume credentials internally, such as `npm run auth:zerodha` or the local Zerodha MCP server, as long as their output does not expose secret values.
- Verify credential presence only through masked/status-style commands or scripts that return `SET` / `MISSING`.
- If credential debugging is needed, ask the user to inspect or rotate values manually instead of reading them.

The Zerodha MCP for this folder must remain project-local. Do not add it to
`~/.codex/config.toml`; use `./bin/codex-zerodha`.
