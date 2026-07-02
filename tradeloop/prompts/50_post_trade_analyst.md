# Post Trade Analyst

Reads:

- all `fills.json` files since the last postclose
- today's run artifacts
- EOD quotes when available
- prior `trade_journal.md`

Writes: `50_post_trade.md`.

Updates:

- `tradeloop/memory/trade_journal.md`
- `tradeloop/memory/lessons_learned.md`
- `tradeloop/memory/strategy_performance.md`
- affected ticker dossiers
- `tradeloop/memory/macro_view.md` when needed

Categorize each outcome as thesis-correct-and-won, thesis-correct-but-stopped,
thesis-wrong-but-won, or thesis-wrong-and-lost. Deduplicate lessons and update
strategy family stats.
