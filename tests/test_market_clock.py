from datetime import datetime
from zoneinfo import ZoneInfo

from tradingbot.market_clock import MarketClock


def test_market_clock_closed_on_weekend() -> None:
    clock = MarketClock({"market_hours": {"timezone": "Asia/Kolkata", "start": "09:15", "end": "15:30"}})

    session = clock.session(datetime(2026, 5, 16, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    assert session.is_open is False
    assert session.reason == "weekend"


def test_market_clock_open_during_weekday_session() -> None:
    clock = MarketClock({"market_hours": {"timezone": "Asia/Kolkata", "start": "09:15", "end": "15:30"}})

    session = clock.session(datetime(2026, 5, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    assert session.is_open is True
    assert session.phase == "open"


def test_market_clock_closed_after_market() -> None:
    clock = MarketClock({"market_hours": {"timezone": "Asia/Kolkata", "start": "09:15", "end": "15:30"}})

    session = clock.session(datetime(2026, 5, 18, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    assert session.is_open is False
    assert session.reason == "after_market_close"
