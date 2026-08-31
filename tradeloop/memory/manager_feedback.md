# Manager Feedback

## 2026-08-25_0900_premarket route-outcome 1 TARIL

_run_id: 2026-08-25_0900_premarket · 2026-08-25T09:42:31.350596+05:30 · hash: 61c821fd094b_

event: route_outcome
symbol: TARIL
final_status: RISK_REJECTED
routed_mode: blocked
side: BUY
quantity: 79
price: 303.25
strategy_family: 20d_breakout
reasons: max_sector_allocation_exceeded

## 2026-08-25_0900_premarket route-outcome 2 DALBHARAT

_run_id: 2026-08-25_0900_premarket · 2026-08-25T09:42:31.350596+05:30 · hash: 29a65446c8f7_

event: route_outcome
symbol: DALBHARAT
final_status: FILLED
routed_mode: paper
side: BUY
quantity: 12
price: 1853.0
strategy_family: ema20_pullback
reasons:

## 2026-08-27_0900_premarket conviction-blocked 1 HOMEFIRST

_run_id: 2026-08-27_0900_premarket · 2026-08-27T11:01:34.013949+05:30 · hash: 6431dab4727a_

event: conviction_gate_blocked
symbol: HOMEFIRST
side: BUY
quantity: 20
price: 1197.1
strategy_family: 20d_breakout
threshold: 6.5
reason: conviction_below_threshold min=6.5 [HOMEFIRST=5.0]
manager_retry_event: conviction_gate_blocked
manager_retry_status: still_blocked
manager_retry_block_reason:
