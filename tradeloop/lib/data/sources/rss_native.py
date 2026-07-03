from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import feedparser
import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id


def fetch_rss(http: Http, feed_url: str, source: str, tier: str, limit: int = 25) -> List[RawItem]:
    try:
        resp = http.get(feed_url)
    except httpx.HTTPError:
        return []
    if resp.status not in (200,) or not resp.body:
        return []
    parsed = feedparser.parse(resp.body)
    items: List[RawItem] = []
    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        guid = (entry.get("id") or link).strip()
        pub = (entry.get("published") or datetime.now(timezone.utc).isoformat()).strip()
        if not title:
            continue
        items.append(RawItem(
            news_id=news_id(guid, link, title),
            title=title, url=link, source=source, tier=tier, published_at=pub,
        ))
    return items
