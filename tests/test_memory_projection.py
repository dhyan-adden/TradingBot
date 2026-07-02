from pathlib import Path

from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.agents.schemas import PortfolioDecision, PortfolioRating
from tradingbot.event_log import EventLog
from tradingbot.memory.projections import MemoryProjector


def test_memory_projection_dry_run_reports_change(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    event_log.append_event(
        "market.quote_received",
        "QUOTE-RELIANCE",
        {"symbol": "RELIANCE", "last_price": 100},
        created_at="2026-05-16T00:00:00+00:00",
    )
    projector = MemoryProjector(event_log, tmp_path / "memory")

    results = projector.regenerate_daily(dry_run=True)

    assert len(results) == 1
    assert results[0].changed is True
    assert not results[0].path.exists()


def test_scorecard_projection_is_idempotent(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    broker = PaperBroker(event_log, starting_cash_inr=1000)
    broker.place_order(PaperOrderRequest("RELIANCE", "BUY", 1, 100))
    projector = MemoryProjector(event_log, tmp_path / "memory")

    first = projector.regenerate_scorecard(broker)
    second = projector.regenerate_scorecard(broker)

    assert first.changed is True
    assert second.changed is False


def test_daily_projection_ignores_projection_events(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    event_log.append_event(
        "market.quote_received",
        "QUOTE-RELIANCE",
        {"symbol": "RELIANCE", "last_price": 100},
        created_at="2026-05-16T00:00:00+00:00",
    )
    projector = MemoryProjector(event_log, tmp_path / "memory")

    first = projector.regenerate_daily()
    second = projector.regenerate_daily(dry_run=True)

    assert first[0].changed is True
    assert second[0].changed is False


def test_portfolio_decision_projection(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    projector = MemoryProjector(event_log, tmp_path / "memory")
    decision = PortfolioDecision(
        symbol="RELIANCE",
        rating=PortfolioRating.HOLD,
        executive_summary="Observe only.",
        investment_thesis="Paper harness validation is still underway.",
    )

    result = projector.write_portfolio_decision(decision, "DECISION-RELIANCE-20260516")

    assert result.changed is True
    assert result.path.exists()
    assert "rating: Hold" in result.path.read_text(encoding="utf-8")
