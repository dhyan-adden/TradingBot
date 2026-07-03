from __future__ import annotations

import json
from typing import List

import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id

_SOURCE = {"IndianStreetBets": "reddit_indianstreetbets", "IndiaInvestments": "reddit_indiainvestments"}


def fetch_reddit(http: Http, subreddits: List[str], limit: int = 25) -> List[RawItem]:
    items: List[RawItem] = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
        try:
            resp = http.get(url)
        except httpx.HTTPError:
            continue
        if resp.status != 200 or not resp.body:
            continue
        try:
            payload = json.loads(resp.body)
        except (ValueError, json.JSONDecodeError):
            continue
        for child in payload.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = (d.get("title") or "").strip()
            if not title:
                continue
            link = "https://www.reddit.com" + d.get("permalink", "")
            guid = d.get("id", "") or link
            items.append(RawItem(
                news_id=news_id(guid, link, title),
                title=title, url=link,
                source=_SOURCE.get(sub, f"reddit_{sub.lower()}"), tier="tier_C",
                published_at=str(d.get("created_utc", "")),
            ))
    return items
