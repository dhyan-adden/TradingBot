from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MoneycontrolItem:
    query: str
    title: str
    url: str
    source: str = "moneycontrol_placeholder"


def fetch_moneycontrol_news(query: str, limit: int = 10) -> List[MoneycontrolItem]:
    """Placeholder for a future Moneycontrol RSS/scraper adapter.

    Keep this deterministic and explicit: callers can depend on an empty list
    instead of accidental scraping behavior until the source contract is locked.
    """

    return []
