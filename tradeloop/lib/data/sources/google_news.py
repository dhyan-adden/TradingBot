from __future__ import annotations

import html
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List

import httpx

from tradeloop.lib.data.http import Http
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.snapshot import news_id


def _parse_rss(body: bytes, source: str, tier: str, limit: int) -> List[RawItem]:
    root = ET.fromstring(body)
    items: List[RawItem] = []
    for node in root.findall("./channel/item")[:limit]:
        title = html.unescape(node.findtext("title", default="")).strip()
        link = node.findtext("link", default="").strip()
        guid = node.findtext("guid", default="").strip()
        pub = node.findtext("pubDate", default="").strip() or datetime.now(timezone.utc).isoformat()
        if not title:
            continue
        items.append(RawItem(
            news_id=news_id(guid, link, title),
            title=title, url=link, source=source, tier=tier, published_at=pub,
        ))
    return items


def fetch_google_news(http: Http, query: str, limit: int = 15) -> List[RawItem]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = http.get(url)
    except httpx.HTTPError:
        return []
    if resp.status != 200 or not resp.body:
        return []
    return _parse_rss(resp.body, source="google_news_generic", tier="tier_C", limit=limit)
