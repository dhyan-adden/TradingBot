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
[ordered subset of exactly these filenames - no other values are valid:
`10_news.md`, `11_sentiment.md`, `12_fundamentals.md`, `13_technical.md`,
`14_shortlist.md`, `20_bull.md`, `21_bear.md`, `22_debate.md`,
`30_trade_plan.md`, `40_risk_report.md`, `41_pm_decision.md`]

## Refused Or Ignored Parts
[unsafe or out-of-scope pieces, if any]
```

