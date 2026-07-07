from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from tradeloop.lib.broker.orders_schema import to_ticket
from tradeloop.lib.risk.checks import RiskCaps, RiskState, evaluate


@dataclass(frozen=True)
class Deficiency:
    symbol: str
    severity: str        # material_weakness | significant_deficiency | deficiency
    kind: str
    detail: str


@dataclass(frozen=True)
class ControlReport:
    tested: int
    passed: int
    deficiencies: List[Deficiency]


def _fill_index(fills: List[dict]) -> Dict[str, List[dict]]:
    index: Dict[str, List[dict]] = {}
    for f in fills:
        symbol = str(f.get("payload", {}).get("symbol", "")).strip().upper()
        index.setdefault(symbol, []).append(f)
    return index


def recheck(orders, fills: List[dict], caps: RiskCaps, state: RiskState) -> ControlReport:
    """SOX-style control test: independently re-run evaluate() over each order and
    cross-check the routing outcome recorded in fills.json."""
    index = _fill_index(fills)
    deficiencies: List[Deficiency] = []
    passed = 0

    for order in orders.orders:
        ticket = to_ticket(order)
        symbol = ticket.symbol.strip().upper()
        verdict = evaluate(ticket, state, caps)
        matched = index.get(symbol, [])
        filled = any(str(f.get("status", "")).upper() == "FILLED" for f in matched)
        rejected_recorded = any(str(f.get("status", "")).upper() == "RISK_REJECTED" for f in matched)

        if not verdict.approved:
            if filled:
                deficiencies.append(Deficiency(symbol, "material_weakness", "bad_order_filled",
                                               "gate should have rejected: " + ",".join(verdict.reasons)))
            elif not rejected_recorded:
                deficiencies.append(Deficiency(symbol, "deficiency", "missing_audit_record",
                                               "rejected order has no RISK_REJECTED record: " + ",".join(verdict.reasons)))
            else:
                passed += 1
        else:
            if rejected_recorded:
                deficiencies.append(Deficiency(symbol, "significant_deficiency", "verdict_outcome_mismatch",
                                               "order re-evaluates as approved but was recorded RISK_REJECTED"))
            else:
                passed += 1

    return ControlReport(tested=len(orders.orders), passed=passed, deficiencies=deficiencies)
