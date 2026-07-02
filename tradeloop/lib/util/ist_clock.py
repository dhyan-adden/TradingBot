from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class MarketSession:
    is_open: bool
    phase: str
    local_time: str


def now_ist() -> datetime:
    return datetime.now(IST)


def market_session(now: datetime | None = None) -> MarketSession:
    current = now.astimezone(IST) if now else now_ist()
    if current.weekday() >= 5:
        return MarketSession(False, "weekend", current.isoformat())
    if current.time() < time(9, 15):
        return MarketSession(False, "pre_market", current.isoformat())
    if current.time() > time(15, 30):
        return MarketSession(False, "post_market", current.isoformat())
    return MarketSession(True, "open", current.isoformat())

