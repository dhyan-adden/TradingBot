# Ad Hoc Intake

Reads:

- `user_request.md`
- `00_context.md`
- shared market, memory, and schema prompts

Writes: `05_adhoc_intake.md`.

Classify the request as one of:

- `market_research`
- `ticker_dossier`
- `portfolio_management`
- `full_trade_request`

Rules:

- Keep India cash-equity, long-only policy active.
- If the request asks for short selling, F&O, NRML, leverage, or non-India
  instruments, refuse that part and continue with any safe long-only research.
- If the request is `full_trade_request`, run the complete pipeline through PM,
  risk, `orders.json`, and broker routing.
- If the request is research-only, write the relevant analysis artifacts and
  leave `orders.json` as `[]`.

Output:

```markdown
## Classification
[one of the allowed labels]

## Safe Interpretation
[what TradeLoop will do]

## Required Stages
[ordered list of downstream files to write]

## Refused Or Ignored Parts
[unsafe or out-of-scope pieces, if any]
```

