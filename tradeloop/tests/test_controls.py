from tradeloop.lib.audit.controls import ControlReport, recheck
from tradeloop.lib.broker.orders_schema import Order, OrdersFile
from tradeloop.lib.risk.checks import RiskCaps, RiskState


def _caps():
    return RiskCaps(
        capital_inr=100000.0,
        max_open_positions=4,
        max_position_allocation_pct=25,
        max_total_deployed_pct=90,
        max_sector_allocation_pct=40,
        max_daily_drawdown_pct=3,
        universe=["TCS", "INFY"],
        min_position_size_inr=15000,
    )


def _state():
    return RiskState(cash_inr=100000.0, positions={}, avg_prices={}, sectors={"TCS": "IT", "INFY": "IT"})


def _fill(symbol, status, mode="paper", reasons=None):
    payload = {"symbol": symbol}
    if reasons is not None:
        payload["reasons"] = reasons
    return {"mode": mode, "status": status, "payload": payload}


def test_clean_run_no_deficiencies():
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=100, price=200.0)])
    fills = [_fill("TCS", "FILLED")]
    report = recheck(of, fills, _caps(), _state())
    assert isinstance(report, ControlReport)
    assert report.deficiencies == []
    assert report.tested == 1 and report.passed == 1


def test_bad_order_that_filled_is_material_weakness():
    # non-universe symbol that nevertheless FILLED -> gate leaked
    of = OrdersFile(mode="premarket", orders=[Order(ticker="ZZZZ", side="BUY", quantity=100, price=200.0)])
    fills = [_fill("ZZZZ", "FILLED")]
    report = recheck(of, fills, _caps(), _state())
    assert any(d.severity == "material_weakness" and "symbol_not_in_universe" in d.detail for d in report.deficiencies)


def test_rejected_order_missing_audit_record_is_deficiency():
    # correctly a bad order (oversized), but NO RISK_REJECTED fill recorded
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=1000, price=200.0)])
    fills = []  # nothing routed / recorded
    report = recheck(of, fills, _caps(), _state())
    assert any(d.severity == "deficiency" and d.kind == "missing_audit_record" for d in report.deficiencies)


def test_correctly_rejected_and_recorded_is_clean():
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=1000, price=200.0)])
    fills = [_fill("TCS", "RISK_REJECTED", mode="blocked", reasons=["max_position_allocation_exceeded"])]
    report = recheck(of, fills, _caps(), _state())
    assert report.deficiencies == []
    assert report.tested == 1 and report.passed == 1
