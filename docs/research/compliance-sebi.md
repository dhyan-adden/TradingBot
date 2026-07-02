# SEBI/NSE Compliance Notes

## V1 Interpretation

The first version is paper trading only. It does not place live exchange orders
and does not need an algo ID or live order approval flow. Still, the system is
designed as if live migration will eventually require auditability, broker
controls, static IP constraints, and traceable algorithm behavior.

## Design Requirements

- Keep a complete audit trail of every decision and simulated order lifecycle.
- Keep live execution disabled by default.
- Maintain a hard paper/live boundary in config and code.
- Keep all analyst/researcher/trader/portfolio-manager agents advisory only.
- Preserve broker/API session assumptions, including daily Zerodha access-token
  renewal.
- Implement order-rate protection before live trading is considered.
- Keep strategy, risk, and agent decisions traceable to config hashes.
- Never allow agents to read local secrets.

## Live Trading Later

Before live trading, add a separate compliance review for:

- Static IP configuration and broker registration.
- Algo tagging and order traceability.
- Broker-provided controls and kill switch.
- Rate limits and order-per-second guardrails.
- Market-order protection and rejection handling.
- Postback/order-update reconciliation.

Sources:

- SEBI circular: https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- SEBI implementation timeline extension: https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf
- NSE implementation standards: https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf
