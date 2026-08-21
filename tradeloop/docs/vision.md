# TradeLoop Vision, Evidence Base, and Architecture Decisions

Written 2026-07-15/16.
Supersedes the first draft of this document.
Every load-bearing decision below cites evidence that was adversarially verified: claims were extracted from primary sources and independent verification passes attempted to refute each one against the original documents.
25 key claims were verified this way; zero were refuted.
Where evidence is thin, contested, or practitioner-grade, the decision says so explicitly and the confidence level reflects it.

## 1. The vision

TradeLoop becomes an evidence-gated hybrid fund:

- a mechanical signal core whose every rule has survived a bias-controlled backtest,
- sized by a regime-aware exposure governor,
- with the LLM agent stack repositioned as a bounded research overlay that must continuously prove it adds alpha against a recorded mechanical baseline,
- running on an accountability spine (hash-chained ledger, reconciliation, attribution) that already exists,
- with operations hardened against the silent failures that actually kill retail algo setups.

The system never asks "do we believe this strategy works?".
It asks "what does the trial-adjusted out-of-sample evidence say, and what does the counterfactual ledger say?".

## 2. What the evidence says (verdicts by question)

### 2.1 Backtest validation methodology - confidence: HIGH

All claims verified 3-0 against primary sources.

- The Deflated Sharpe Ratio corrects for exactly the two inflation sources that will threaten our lab: selection bias under multiple testing, and non-normal returns ([Bailey and Lopez de Prado, JPM 2014](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)).
- A backtest that does not record the number of trials attempted is, in the authors' words, "worthless, regardless of how excellent the reported performance might be".
- The expected maximum Sharpe across N trials grows with N even at zero true skill; with 5 years of daily data, 45+ strategy variations make a spurious in-sample Sharpe of 1.0+ more likely than not ([Bailey et al. 2015](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf)).
- In 400 zero-edge simulations, parameter sweeps (~55,000 combinations) produced in-sample Sharpe ~0.9 vs out-of-sample ~0.0. No fixed Sharpe haircut is safe; only trial-aware corrections (DSR/PBO) are.
- Combinatorial Purged Cross-Validation (CPCV) beat walk-forward, K-fold, and purged K-fold at preventing false discoveries (lower PBO, better DSR) in a controlled comparison ([Arian, Norouzi, Seco 2024](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)). Walk-forward - the retail default - was specifically weak. Caveat: the ranking comes from synthetic markets plus S&P validation, not Indian equities, so we use CPCV for selection and walk-forward as a secondary confirmation, not as the sole gate.

### 2.2 Point-in-time NSE data - confidence: HIGH on the problem, MODERATE on the reconstruction method

- Survivor-only backtesting on the NIFTY Smallcap 250 overstates annual returns by 4.94 percentage points (23.3% relative) and Sharpe by 0.097 over 2016-2025 (verified 3-0, [arXiv:2603.19380](https://arxiv.org/abs/2603.19380)).
- That index churned 82.5% of constituents in nine years: 16.1% delisted, 33.1% graduated to bigger indices, 33.2% demoted (verified 3-0). A point-in-time universe must therefore handle index migration, not just delistings.
- NSE bhavcopy archives include delisted securities and support reconstructing historical membership by market-cap/price-volume ranking with ~100% accuracy for current constituents and an estimated 85-90% historically (verified against the paper's abstract; single recent preprint, hence MODERATE).
- The Kite historical API cannot be the historical backbone (verified against [the official docs](https://kite.trade/docs/connect/v3/historical/)): the docs state no lookback depth ("several years"), document no corporate-action adjustment policy at all, and the expired-instrument facility (`continuous`) exists only for NFO/MCX futures - there is no delisted-equity history. Forum guidance (secondary): minute data starts ~2015, daily depth varies per symbol, ~2000-day chunks, 3 req/s.
- Verified Zerodha CNC cost reality ([official charges page](https://zerodha.com/charges/)): zero brokerage; STT 0.1% on BOTH buy and sell; stamp 0.015% buy-side; NSE transaction charge 0.00307%; SEBI Rs 10/crore; GST 18% on (brokerage + SEBI + transaction charges); DP Rs 15.34 per scrip on every sell.
- Consequence found in our code: `lib/broker/cost_model.py` charges CNC STT on the sell leg only - the paper ledger has been understating round-trip costs by ~0.1% of buy turnover, and exchange transaction + SEBI charges are unmodeled. Fix listed in Phase 0.
- The Rs 15.34 fixed DP charge is 10bps on our Rs 15,000 minimum position - small positions are structurally more expensive; the lab must price this per-trade, not as a percentage.

### 2.3 Regime detection for exposure scaling - confidence: HIGH against volatility targeting, MODERATE for trend/breadth filters

- Volatility-managed portfolios do NOT systematically beat unmanaged ones across 103 equity strategies, and real-time implementable versions generally earn LOWER certainty-equivalent returns and Sharpe than doing nothing, due to structural instability in the underlying regressions ([Cederburg, O'Doherty, Wang, Yan, JFE 2020](https://www.lehigh.edu/~xuy219/research/COWY.pdf)). Volatility targeting is therefore rejected as our regime mechanism.
- FINSABER's regime analysis concludes trend detection and regime-aware risk controls matter more than framework complexity (verified, [arXiv:2505.07078](https://arxiv.org/abs/2505.07078)).
- Trend-filter evidence (index above/below 200DMA, breadth) is largely practitioner-grade rather than peer-reviewed - flagged honestly as MODERATE.
- The India-specific data point that makes a regime governor non-optional for us: an 18.5-year point-in-time NSE momentum backtest ([backtestindia.com](https://backtestindia.com/blog/quality-momentum-india-backtest), practitioner source) shows even quality-filtered momentum drew down -61.7% in 2008, worse than the Nifty 50's -55.1%. Long-only momentum without exposure control is how an account dies once per cycle.
- Decision consequence: a simple trend/breadth exposure multiplier, validated in our own lab before it touches sizing. If it fails our backtest, it does not ship.

### 2.4 Where LLMs add or subtract value - confidence: HIGH on the skeptical core

- FINSABER (KDD 2026, all four claims verified verbatim against the abstract): two decades, 100+ symbols; previously reported LLM advantages "deteriorate significantly" under broad evaluation; LLM strategies are "overly conservative in bull markets, underperforming passive benchmarks, and overly aggressive in bear markets, incurring heavy losses".
- LiveTradeBench ([arXiv:2511.03628](https://arxiv.org/abs/2511.03628)): 21 LLMs, 50 live days; general benchmark ability does not predict trading performance (slightly negative correlation); documented news-overreaction failure mode; and notably NO mechanical baseline comparison was reported - so even its positive numbers prove little.
- Knowledge-cutoff contamination: models recall in-training prices (Lopez-Lira et al., cited via [arXiv:2601.13770](https://arxiv.org/pdf/2601.13770)); in that preprint's tests, standard LLM agents lost 15+ percentage points of alpha out-of-cutoff while a simple 3-month momentum baseline kept +5.75pp with minimal decay (single-author preprint on 5 tickers - thin, flagged; direction is consistent with FINSABER and FinLeak-Bench).
- Structural consequence: LLMs are never inside a backtest loop (any LLM-in-the-loop backtest is contaminated by memorized history) - so only the mechanical core is backtestable, and the LLM overlay can only be judged FORWARD, against a recorded counterfactual baseline. That is exactly what the counterfactual ledger provides.
- What LLMs remain plausibly good for (unproven as alpha, cheap to keep bounded): reading news/filings into structured catalysts, eligibility screening, vetoing mechanically-valid-but-news-toxic entries, and post-trade journaling. Each intervention is logged and scored against the baseline; the overlay keeps its authority only while its measured alpha is non-negative.

### 2.5 Sizing and portfolio construction - confidence: LOW-to-MODERATE (keep it simple)

- No strong academic winner among fixed-fractional vs ATR-anchored vs vol-scaled position sizing for 3-20 day holds; vol-scaled sizing inherits the volatility-management OOS problem above.
- Our existing structure (1.5% risk per trade, ATR-anchored stops, 4% max open heat, max 4 positions, 25% position cap, 1% ADV participation cap) matches standard practitioner risk discipline; nothing in the evidence argues for redesign.
- Stop placement (currently 1.5x ATR) and target structure (2R/3R) become lab parameters within tight, pre-registered grids - selected by CPCV, deflated by DSR - not constants asserted by hand and not free-roaming sweeps.

### 2.6 Indian momentum/swing edges - confidence: HIGH that momentum exists gross; MODERATE after costs; PEAD CONTESTED

- Momentum exists in India: significant intermediate/long-term price momentum across 3,956 BSE stocks over 2000-2021 ([Pacific-Basin Finance Journal](https://www.sciencedirect.com/science/article/abs/pii/S0927538X23002640)); industry-level momentum robust across horizons ([Global Business Review 2015](https://ideas.repec.org/a/sae/globus/v16y2015i3p494-510.html)).
- Momentum concentrates in LIQUID stocks; illiquid names show reversals instead. Our Rs 5cr turnover floor is not just execution hygiene - it is where the edge lives.
- After costs, the best available point-in-time NSE evidence is practitioner-grade: 12-month momentum on the top-200 universe returned ~14.0% net CAGR vs 10.4% Nifty 50 over 2006-2025, ~18% with quality filters (backtestindia.com; optimistic cost assumptions; MODERATE confidence).
- Academic studies are long-short and gross-of-costs; our long-only CNC implementation must prove its own after-cost edge in the lab. No published result substitutes for that.
- PEAD on NSE is CONTESTED: one study finds a significant 4.8pp drift over 64 trading days for high-surprise Nifty 500 deciles (2002-2017, gross, long leg still +3.7% post-2008, [SCIRP](https://www.scirp.org/journal/paperinformation?paperid=88060)); another finds NO exploitable drift and even negative association in 100 large NSE firms 2014-2018 ([econstor](https://www.econstor.eu/handle/10419/308924)). Additionally the documented drift accrues over ~3 months, which mismatches our 5-15 day holding spec.
- Consequence: `post_earnings_drift` and `results_day_momentum` are demoted to hypothesis status - they trade only if they clear the lab with margin, and their horizon spec may need to change to match where the drift actually lives.

### 2.7 Operational reliability - confidence: MODERATE (practitioner sources, convergent, matches our own incident history)

- The dominant production failure mode is SILENT: stale data that looks valid, feeds that die while the connection reports healthy, orders "cancelled" that are still live, schedulers that quietly stop firing ([Concretum](https://concretumgroup.com/building-reliable-trading-systems-algorithmic-trading-automation/), [ElectronicTradingHub](https://electronictradinghub.com/brokerages-suck-navigating-the-challenges-of-live-algo-trading/)). We lived this twice: cron dead for two months (TCC), and the stale-token empty-scan gap.
- Zerodha access tokens expire daily with no refresh mechanism; auth is a monitored single point of failure, not fire-and-forget. We have headless re-auth; it must alert on failure.
- Paper environments do not enforce all live rules (documented IBKR example), so paper success alone cannot fully qualify a strategy - the promotion ladder needs a small-size live pilot stage.
- On restart, reconcile against broker records before trading (we have `reconcile.py`); keep the audit trail local because broker order history can be truncated (we have the hash ledger).

## 3. Architecture decisions

### ADR-1: All mechanical signal changes gate through an offline Validation Lab

Decision: no rule (family, parameter, filter, regime multiplier) reaches paper or live routing without a lab verdict: CPCV-selected, walk-forward-confirmed, DSR-deflated using the recorded trial count, PBO reported.
The lab maintains a trial ledger: every configuration ever evaluated is recorded (config hash, parameter set, period, result) so deflation is computable and honest.
Alternatives rejected: single holdout (data snooping), walk-forward alone (weakest at false-discovery prevention per 2.1), TradingView/Pine backtesting (forks the rule logic and cost math into a second implementation).
Consequence: slower iteration on signals, and that is the point.

### ADR-2: Historical backbone = NSE bhavcopy archives; Kite = recent bars and live only

Decision: build a local point-in-time store from daily NSE bhavcopy files (which include delisted securities), plus a corporate-action adjustment engine (splits/bonuses) built from NSE corporate-action data, plus point-in-time universe reconstruction by turnover/market-cap ranking.
Kite fills recent gaps and serves live cycles; it is disqualified as the historical backbone by its own documentation (no delisted equities, no stated depth, no stated adjustment policy - 2.2).
Kite's actual adjustment behavior gets verified empirically against known split events before any of its bars enter the store.
Alternatives rejected: Kite-only (survivorship bias, quantified at ~5pp/year in small caps), paid NSE EOD subscription (not self-serve, unclear depth; revisit only if bhavcopy ingestion proves insufficient), third-party vendors (unverified adjustment quality; possible later addition for cross-checking).

### ADR-3: The five strategy families become deterministic, pre-registered rule specs

Decision: each family is specified fully mechanically (universe filter, entry, stop, target, horizon, exits), with parameter grids pre-registered before any backtest runs.
Evidence alignment: momentum-flavored families (breakout, EMA trend pullback, sector rotation leader) have supporting India evidence; PEAD-flavored families are contested and enter as hypotheses (2.6).
The scanner currently implements only 2 of 5 families mechanically; the other three exist as LLM behavior and are therefore currently unvalidatable - formalizing them is a prerequisite to testing them.
Families that fail the lab are removed from the scanner, not argued with.

### ADR-4: Regime governor = trend/breadth exposure multiplier; volatility targeting rejected

Decision: a deterministic exposure multiplier in {1.0, 0.5, 0.0} from Nifty 500 vs its 200DMA plus universe breadth (% above 200DMA), computed in the prepare step, applied by the sizing layer to new entries, visible in every run context and on the dashboard.
It ships only after passing the lab on the point-in-time store (MODERATE evidence in, our own backtest decides).
Volatility targeting is rejected on HIGH-confidence peer-reviewed out-of-sample failure (2.3).
Consequence: in bear regimes the system's correct behavior is to do little or nothing new; the approval queue going quiet is a feature.

### ADR-5: LLM overlay is bounded, forward-scored, and never inside a backtest

Decision: the agent stack keeps exactly three authorities: catalyst detection/eligibility (news tiers), veto or downsize (never upsize) of mechanically-valid candidates, and post-trade journaling.
Every cycle records the counterfactual: what the mechanical core plus regime governor would have done alone, alongside what the overlay actually decided; both tracks are scored by the existing outcome scorer.
Overlay alpha is reported per team over a rolling 60-trade window; two consecutive negative windows demote the overlay to journaling-only automatically.
Backtests never contain an LLM call (knowledge-cutoff contamination, 2.4).
Alternatives rejected: LLM-as-signal-generator (FINSABER regime failure modes, both directions), more agents/bigger models (LiveTradeBench: capability does not transfer; blocked until the scoreboard is positive).

### ADR-6: Sizing scheme unchanged; parameters become lab-validated

Decision: keep fixed-fractional risk with ATR-anchored stops and the existing heat/position/ADV caps; expose stop multiple and target multiples as pre-registered lab grid parameters rather than constants.
No volatility-scaled sizing (2.3, 2.5).
Minimum position size gets re-derived in the lab from the fixed-cost reality (Rs 15.34 DP per sell plus slippage tiers) instead of asserted.

### ADR-7: One cost model, corrected, shared by replay and production

Decision: fix `cost_model.py` per the verified charge sheet - STT 0.1% on BOTH CNC legs (bug: currently sell-only), add exchange transaction charge 0.00307% and SEBI Rs 10/crore into the GST base, update DP to Rs 15.34 - and have the lab's replay engine import this exact module so backtest money math and production money math cannot diverge.
Slippage stays tiered by liquidity segment as configured, and is stress-tested in the lab at 2x assumed values; a strategy that dies at 2x slippage is not promoted.

### ADR-8: Ops hardening against silent failure

Decision, in priority order:
a dead-man alert when a scheduled cycle does not produce its run directory on time;
an alert when headless auth fails (auth is a monitored SPOF);
freshness stamps on every data input with deterministic halt-on-stale (a scan from stale data is DATA-BLOCKED, never a quiet HOLD - codifying the lesson of the empty-scan incident);
restart reconciliation stays mandatory before any routing;
VPS/container migration decided after the lab exists - a laptop-independent runtime removes the Mac-awake dependency that has already bitten once.

### ADR-9: Promotion ladder with three gates per family

Decision: live capital follows family-level promotion: (1) lab verdict - positive out-of-sample expectancy after corrected costs with DSR indicating the result is unlikely to be a selection artifact given the logged trial count; (2) the existing paper gates (40 trades, 45% win rate, 0.3R expectancy, 8% max drawdown) tracked per family; (3) a live pilot at minimum viable size, because paper environments provably do not enforce all live rules.
Demotion on breach is automatic and needs no meeting.

## 4. Target architecture

```text
+------------------------------------------------------------------------+
| OPS: launchd now -> container/VPS later; dead-man alerts; auth alerts;  |
|      freshness stamps + halt-on-stale; health reports                   |
+------------------------------------------------------------------------+
| RISK + EXECUTION (existing): caps, circuit breaker, kill switch,        |
|      AWAITING_APPROVAL gate, paper/live router + promotion ladder,      |
|      hash-chained ledger, restart reconciliation                        |
+------------------------------------------------------------------------+
| LLM OVERLAY (existing agents, bounded): catalyst detection; veto/       |
|      downsize only; journaling. Counterfactual ledger records baseline  |
|      vs actual every cycle; overlay alpha scoreboard; auto-demotion     |
+------------------------------------------------------------------------+
| REGIME GOVERNOR (new): Nifty500 vs 200DMA + breadth -> multiplier       |
|      {1.0, 0.5, 0.0} into sizing; lab-validated before shipping         |
+------------------------------------------------------------------------+
| SIGNAL CORE (formalized): 5 families as pre-registered deterministic    |
|      specs; only lab-promoted families emit candidates                  |
+------------------------------------------------------------------------+
| DATA FOUNDATION (new): bhavcopy point-in-time store incl. delisted;     |
|      corporate-action adjustment engine; PIT universe reconstruction;   |
|      Kite for recent bars + live quotes only                            |
+------------------------------------------------------------------------+
| VALIDATION LAB (new, offline): replay engine importing production       |
|      cost_model + risk checks; CPCV selection; walk-forward             |
|      confirmation; DSR/PBO with mandatory trial ledger                  |
+------------------------------------------------------------------------+
```

## 5. Roadmap

Each phase is independently valuable and ends with a verification step.

### Phase 0 - corrections that should not wait (days)

Fix the CNC STT buy leg in `cost_model.py`; add exchange transaction and SEBI charges; update DP to 15.34.
Add the dead-man alert for missed scheduled cycles and the auth-failure alert.
Verify: cost unit tests against a hand-computed Zerodha contract-note example; a deliberately skipped cycle fires the alert.

### Phase 1 - data foundation (the long pole)

Ingest daily bhavcopy archives into a local point-in-time store including delisted symbols; build the corporate-action adjustment engine; reconstruct point-in-time universes by turnover ranking; empirically test Kite's adjustment behavior against known split/bonus events.
Verify: adjusted series for ~20 symbols with known corporate actions match independent references; a reconstructed 2018 universe passes spot-checks against archived index constituent lists.

### Phase 2 - validation lab

Event-driven replay engine that imports the production cost model and risk checks; CPCV + walk-forward + DSR/PBO harness; trial ledger as an append-only artifact.
Verify: the replay engine reproduces the existing paper ledger's fills and P&L within tolerance before any verdict is trusted.

### Phase 3 - family verdicts

Codify all five families as pre-registered specs with bounded grids; run the lab across regimes (must include 2008 if data depth allows, else 2016-2025 including 2020 and 2022); keep/kill/reshape each family; re-derive stop/target/minimum-position parameters.
Deliverable: a per-family verdict report with out-of-sample stats, DSR, and PBO - the document that decides what this system actually trades.

### Phase 4 - regime governor

Backtest the exposure multiplier on the promoted families; wire it into sizing; surface regime state in run context and dashboard.
Verify: a simulated bear-regime paper cycle sizes new entries to zero.

### Phase 5 - counterfactual ledger and overlay scoreboard

Record baseline vs actual decisions every cycle; extend attribution and the dashboard with per-team overlay alpha; implement auto-demotion.
Verify: one full cycle produces both tracks and the dashboard renders the comparison.

### Phase 6 - promotion ladder and live pilot

Wire lab verdicts into `live_promotion_ready` alongside the existing paper gates; add the minimum-size live pilot stage.
Verify: a family missing a lab verdict cannot route live even with passing paper stats.

### Phase 7 - runtime migration

Containerize the orchestrator; move scheduling off the Mac to a small VPS; keep launchd as fallback.
Verify: one full unattended week of cycles from the VPS with zero missed runs and clean reconciliation.

Explicitly deferred: intraday algo (revisit only after a family holds a live promotion through a full quarter); F&O/short/leverage (never, non-negotiable); additional LLM complexity (blocked until the overlay scoreboard is positive).

## 6. Success metrics and kill criteria

- Lab integrity: 100% of parameter evaluations recorded in the trial ledger; any strategy result published without its trial count is treated as invalid by policy.
- Phase 3 success: at least one family with positive after-cost out-of-sample expectancy whose DSR survives its trial count; failing families are deleted from the scanner.
- Overlay: positive rolling-60-trade alpha keeps authority; two consecutive negative windows demote it to journaling-only, automatically.
- Regime governor: ships only if it improves lab MAR/drawdown on promoted families without destroying net CAGR; otherwise exposure stays at 1.0 and the idea is shelved.
- System: zero unexplained ledger breaks; zero missed scheduled cycles without an alert; live capital only ever enters through the three-gate ladder.

## 7. Sources

Verified primary sources: [Bailey and Lopez de Prado 2014 (DSR)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551); [Bailey et al. 2015 (overfitting)](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf); [Arian et al. 2024 (CPCV)](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110); [arXiv:2603.19380 (NSE survivorship)](https://arxiv.org/abs/2603.19380); [Kite Connect historical docs](https://kite.trade/docs/connect/v3/historical/); [Zerodha charges](https://zerodha.com/charges/); [FINSABER, KDD 2026](https://arxiv.org/abs/2505.07078); [Cederburg et al., JFE 2020](https://www.lehigh.edu/~xuy219/research/COWY.pdf); [LiveTradeBench](https://arxiv.org/abs/2511.03628); [Momentum, reversals and liquidity: Indian evidence](https://www.sciencedirect.com/science/article/abs/pii/S0927538X23002640).
Supporting/secondary: [arXiv:2601.13770 (alpha decay preprint, thin)](https://arxiv.org/pdf/2601.13770); [SCIRP NSE PEAD study](https://www.scirp.org/journal/paperinformation?paperid=88060); [econstor NSE PEAD null result](https://www.econstor.eu/handle/10419/308924); [Global Business Review 2015 (sector momentum)](https://ideas.repec.org/a/sae/globus/v16y2015i3p494-510.html); [backtestindia.com PIT momentum backtest](https://backtestindia.com/blog/quality-momentum-india-backtest); [Concretum reliability lessons](https://concretumgroup.com/building-reliable-trading-systems-algorithmic-trading-automation/); [ElectronicTradingHub broker-API failures](https://electronictradinghub.com/brokerages-suck-navigating-the-challenges-of-live-algo-trading/); Kite forum threads on [data depth](https://kite.trade/forum/discussion/14149/historical-data-retention-policy) and [rate limits](https://kite.trade/forum/discussion/13397/rate-limits).
