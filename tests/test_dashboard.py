from pathlib import Path

from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.dashboard import dashboard_payload
from tradingbot.event_log import EventLog


def copy_configs(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for source in Path("config").glob("*.yaml"):
        text = source.read_text(encoding="utf-8")
        text = text.replace("state/trading.db", str(tmp_path / "state" / "trading.db"))
        text = text.replace("memory_root: memory", f"memory_root: {tmp_path / 'memory'}")
        (config_dir / source.name).write_text(text, encoding="utf-8")
    return config_dir


def test_dashboard_payload_reports_paper_state(tmp_path: Path) -> None:
    config_dir = copy_configs(tmp_path)
    event_log = EventLog(tmp_path / "state" / "trading.db")
    broker = PaperBroker(event_log, starting_cash_inr=100000)
    broker.place_order(PaperOrderRequest("RELIANCE", "BUY", 1, 1000))
    broker.mark_to_market("RELIANCE", 1015, "test")

    payload = dashboard_payload(config_dir)

    assert payload["portfolio"]["cash_inr"] == 99000
    assert payload["portfolio"]["open_positions"] == 1
    assert payload["portfolio"]["positions"][0]["unrealized_pnl_inr"] == 15
    assert payload["system"]["event_count"] == 4
    assert "loop" in payload
    assert payload["order_gate"]["mode"] == "autopilot"
    assert payload["order_gate"]["pending"] == []
