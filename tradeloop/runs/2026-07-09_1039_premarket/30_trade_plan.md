# Trade Plan - 2026-07-09 Premarket

## Cycle Constraint (governs every decision below)

`02_setups_raw.md` is EMPTY this cycle - the Kite universe scan failed on an auth-token timing error at ~08:09 IST (confirmed by 13_technical.md and 22_debate.md).
Per the price-grounding hard rule, `entry`/`hard_stop`/`target_1`/`target_2` MUST come from a ticker's line in `02_setups_raw.md`.
There are no setup lines, so there are no live ATR stop scaffolds for any name.
A debated name with no scan setup cannot be sized, so I do NOT propose it - I carry it as `held`/watch with a reason.

**New-entry tickets this cycle: ZERO.** `orders.json` remains empty on the new-entry side.
Memory consulted: `lessons_learned.md` (empty), `strategy_performance.md` (one RELIANCE skip, no completed trades - no strategy-family weighting available). Nothing in durable memory changes these decisions.

---

## New-Entry Candidates - Carried as Watch (no ticket, scan gap)

| Ticker | Debate verdict | Conviction | Carry-forward reason (no ticket possible) |
|--------|----------------|-----------|--------------------------------------------|
| ICICIBANK | watch | 6.0/10 | Strongest, cleanest thesis in the shortlist - GREEN fundamentals plus confirmed relative strength vs PSU peers on a risk-off tape. No live ATR stop exists this cycle and the intraday high (1403.60) faded back toward 1390, so it cannot be sized. Highest-priority carry-forward for ATR sizing once the scanner is restored. A fade-and-hold below prior close 1380.60 next session would weaken the thesis. |
| INFY | watch | 3.5/10 | Plausible relief-bounce thesis (institutional accumulation, clean balance sheet) but fully gated on a not-yet-known TCS Q1 FY27 read-through into a weak intraday tape (down ~2.1%), with no stop. Do not act until the TCS result tone resolves favourably and the IT tape stabilises; reassess next cycle with scanner ATR levels. |
| TCS | pass | 2.0/10 | Live binary result event today with Tier-A-confirmed US/Europe demand-softness caution, the sole negative sentiment score, active intraday distribution, and no stop. Not carried as a live long candidate. Re-enter the funnel as a fresh name next cycle ONLY if post-result guidance is better than feared and a clean ATR setup emerges. |

No price levels are invented for any of the above. None is ticketable without a fresh scan.

---

## Held Positions - Management Decisions

Both positions are addressed for management only. No scanner setup is required for a HOLD or an exit-only SELL. Neither triggers a proactive exit this cycle.

### HDFCBANK - HOLD (no change)
- Position: qty 30, avg 830.62, hard_stop 807.24.
- Live: LTP 818.10 vs hard_stop 807.24 = +10.86 (+1.3%) above stop. Underwater vs cost by -1.5%, but comfortably above the mechanical exit.
- Read: Technical HOLD-WATCH, fundamentals GREEN. Small gap-up open, intraday recovering toward session high (819), mildly constructive tone. No material negative catalyst (ICICI Securities Tier-B BUY reiteration mildly supportive; ED/Trinamool item is Tier-C noise).
- **Decision: HOLD. Keep the existing hard stop 807.24 as the mechanical exit. Do not add** (price still below cost basis, no scanner MA confirmation of trend resumption). No acute Tier-A/B exit catalyst - no proactive SELL. Monitor for a close above 820-825 to confirm recovery.

### SBIN - HOLD (thin cushion - explicit monitor item)
- Position: qty 23, avg 1042.42, hard_stop 1015.40.
- Live: LTP 1023.50 vs hard_stop 1015.40 = +8.10 (+0.8%) above stop. Underwater vs cost by -1.8%. Above stop but the cushion is thin.
- Read: Technical EXIT-WATCH, fundamentals YELLOW. Gapped up, tagged 1031.70, faded to 1023.50 - not pressing highs. PSU-bank laggard tape vs private peers, plus Iran/Fed risk-off adding MTM pressure on G-Sec portfolios. All SBIN catalysts are Tier-C only.
- **Decision: HOLD - no proactive exit.** Rationale: price is still above the hard stop and there is NO concrete Tier-A/B exit trigger this cycle. An intraday-managed premarket cut with no fresh acute catalyst would front-run the mechanical stop and is not justified. The thin +0.8% cushion is a real risk, so this is flagged as an explicit **MONITOR item for the intraday cycle**: if price breaks below 1019 (today's open/low) on volume, the 1015.40 hard stop is at material risk and the position should be actively watched into the stop. The hard stop 1015.40 remains the mechanical exit. Do not add.

---

## Summary

- **New-entry tickets: ZERO** - `02_setups_raw.md` is empty (scan/auth gap), so no name has a live stop scaffold and none can be sized. No price levels invented.
- **ICICIBANK** carried as `held`/watch (6.0) - highest-priority ATR-sizing candidate next cycle; **INFY** watch (3.5) - gated on TCS read-through; **TCS** pass (2.0) - live binary event, re-evaluate post-result only.
- **HDFCBANK: HOLD** - above hard stop 807.24 by +1.3%, GREEN fundamentals, no exit catalyst; keep stop, do not add.
- **SBIN: HOLD (no proactive exit)** - above hard stop 1015.40 by only +0.8%; no concrete Tier-A/B trigger to justify pre-empting the stop; flagged as an explicit intraday monitor item (tripwire below 1019 on volume), keep stop, do not add.

_Trader | Cycle: 2026-07-09 premarket | Scan gap - zero new entries; both holdings HOLD on existing hard stops; SBIN thin-cushion monitor_
