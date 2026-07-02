import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List


@dataclass(frozen=True)
class NewsItem:
    query: str
    title: str
    url: str
    source: str
    published_at: str


def fetch_google_news(query: str, limit: int = 10, timeout_seconds: int = 10) -> List[NewsItem]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        data = response.read()
    root = ET.fromstring(data)
    items: List[NewsItem] = []
    for item in root.findall("./channel/item")[:limit]:
        title = html.unescape(item.findtext("title", default="")).strip()
        link = item.findtext("link", default="").strip()
        published = item.findtext("pubDate", default="").strip()
        if title:
            items.append(
                NewsItem(
                    query=query,
                    title=title,
                    url=link,
                    source="google_news_rss",
                    published_at=published or datetime.now(timezone.utc).isoformat(),
                )
            )
    return items

