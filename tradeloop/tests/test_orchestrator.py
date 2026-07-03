import importlib
from datetime import date

from tradeloop.lib.util.holidays import NSE_HOLIDAYS_2026, is_nse_holiday


def test_tradeloop_package_is_importable() -> None:
    # tradeloop must be a real importable package (packaging fix), not only
    # reachable via a sys.path hack inside scripts.
    mod = importlib.import_module("tradeloop.lib.broker.paper_broker")
    assert hasattr(mod, "PaperBroker")
    orch = importlib.import_module("tradeloop.orchestrator")
    assert hasattr(orch, "main")


def test_nse_2026_holiday_gate() -> None:
    assert is_nse_holiday(date(2026, 1, 26)) is True   # Republic Day
    assert is_nse_holiday(date(2026, 6, 26)) is True   # Muharram
    assert is_nse_holiday(date(2026, 3, 26)) is True   # Ram Navami (Thu — corrected date)
    assert is_nse_holiday(date(2026, 7, 1)) is False   # ordinary Wednesday
    assert is_nse_holiday(date(2026, 7, 4)) is True    # Saturday — weekend gate
    assert len(NSE_HOLIDAYS_2026) == 16
