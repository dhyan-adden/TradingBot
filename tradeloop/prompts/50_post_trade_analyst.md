# Post Trade Analyst

Reads:

- all `fills.json` files since the last postclose
- today's run artifacts
- EOD quotes when available
- prior `trade_journal.md`

Writes: `50_post_trade.md`.

Writes narrative only (Python owns the machine-parsed stats):

- `tradeloop/memory/trade_journal.md` - narrative note per closed trade
- `tradeloop/memory/lessons_learned.md` - deduplicated lessons
- affected ticker dossiers - narrative context
- `tradeloop/memory/macro_view.md` when needed

Do NOT edit `tradeloop/memory/strategy_performance.md`, expected/realized R, or
provenance stamps: the Python postclose learning loop
(`tradeloop/lib/audit/postclose.py`) computes attribution, classifies each
outcome (thesis-correct-and-won / thesis-correct-but-stopped /
thesis-wrong-but-won / thesis-wrong-and-lost), and OVERWRITES
`strategy_performance.md` from the fills - this is the file the live-promotion
gate reads. The analyst's role is the human-readable story, not the numbers.
