from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CorporateAnnouncement:
    ticker: str
    category: str
    title: str
    url: str
    source: str


def fetch_corporate_announcements(limit: int = 100) -> List[CorporateAnnouncement]:
    """Placeholder for BSE/NSE filings.

    V1 keeps this source explicit and empty until the filing endpoints and rate
    limits are locked. The raw news renderer can still include this section.
    """

    return []

