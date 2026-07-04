from __future__ import annotations

from typing import List

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.sources.rss_native import fetch_rss

# Official corporate-announcement RSS endpoints (tier-A).
NSE_ANN = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
BSE_ANN = "https://www.bseindia.com/data/xml/notices.xml"


def fetch_nse_bse(http: Http, limit: int = 40) -> List[RawItem]:
    items: List[RawItem] = []
    items += fetch_rss(http, NSE_ANN, source="nse_announcements", tier="tier_A", limit=limit)
    items += fetch_rss(http, BSE_ANN, source="bse_announcements", tier="tier_A", limit=limit)
    return items
