import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Protocol


@dataclass(frozen=True)
class ResearchItem:
    symbol: str
    title: str
    url: str
    source: str
    published_at: str
    summary: str = ""


@dataclass(frozen=True)
class ResearchSummary:
    symbol: str
    summary: str
    sources: List[ResearchItem]
    sentiment: str = "neutral"


@dataclass(frozen=True)
class ShortlistCandidate:
    symbol: str
    score: float
    reason: str
    sources: List[str]
    sentiment: str = "neutral"
    mentions: int = 0


class ResearchProvider(Protocol):
    def fetch(self, symbol: str) -> List[ResearchItem]:
        raise NotImplementedError


class GoogleNewsRSSProvider:
    source = "google_news_rss"

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

    def fetch(self, symbol: str) -> List[ResearchItem]:
        return self.search(f"{symbol} NSE stock India", symbol=symbol.upper())

    def search(self, query_text: str, symbol: str = "MARKET", limit: int = 10) -> List[ResearchItem]:
        query = urllib.parse.quote(query_text)
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            data = response.read()
        root = ET.fromstring(data)
        items: List[ResearchItem] = []
        for item in root.findall("./channel/item")[:limit]:
            title = html.unescape(item.findtext("title", default="")).strip()
            link = item.findtext("link", default="").strip()
            published = item.findtext("pubDate", default="").strip()
            if title:
                items.append(
                    ResearchItem(
                        symbol=symbol.upper(),
                        title=title,
                        url=link,
                        source=self.source,
                        published_at=published or datetime.now(timezone.utc).isoformat(),
                    )
                )
        return items

    def scan_market(
        self,
        candidate_symbols: List[str],
        max_shortlist: int,
        query_text: str = "NSE stocks India market today",
        per_symbol_news_limit: int = 3,
    ) -> List[ShortlistCandidate]:
        return scan_market_news(
            provider=self,
            candidate_symbols=candidate_symbols,
            max_shortlist=max_shortlist,
            query_text=query_text,
            per_symbol_news_limit=per_symbol_news_limit,
        )


class StaticResearchProvider:
    def __init__(self, items: List[ResearchItem] | None = None):
        self.items = items or []

    def fetch(self, symbol: str) -> List[ResearchItem]:
        return [item for item in self.items if item.symbol.upper() == symbol.upper()]

    def search(self, query_text: str, symbol: str = "MARKET", limit: int = 10) -> List[ResearchItem]:
        normalized = symbol.upper()
        if normalized == "MARKET":
            return self.items[:limit]
        return self.fetch(normalized)[:limit]

    def scan_market(
        self,
        candidate_symbols: List[str],
        max_shortlist: int,
        query_text: str = "NSE stocks India market today",
        per_symbol_news_limit: int = 3,
    ) -> List[ShortlistCandidate]:
        return scan_market_news(
            provider=self,
            candidate_symbols=candidate_symbols,
            max_shortlist=max_shortlist,
            query_text=query_text,
            per_symbol_news_limit=per_symbol_news_limit,
        )


def summarize_research(symbol: str, items: List[ResearchItem]) -> ResearchSummary:
    if not items:
        return ResearchSummary(
            symbol=symbol.upper(),
            summary="No online headlines were available for this cycle.",
            sources=[],
            sentiment="neutral",
        )

    titles = [item.title for item in items[:5]]
    lowered = " ".join(titles).lower()
    negative_terms = ["fall", "falls", "loss", "probe", "fraud", "down", "cuts", "weak"]
    positive_terms = ["rise", "rises", "profit", "beats", "growth", "up", "wins", "strong"]
    sentiment = "neutral"
    if sum(term in lowered for term in positive_terms) > sum(term in lowered for term in negative_terms):
        sentiment = "positive"
    elif sum(term in lowered for term in negative_terms) > sum(term in lowered for term in positive_terms):
        sentiment = "negative"

    return ResearchSummary(
        symbol=symbol.upper(),
        summary="; ".join(titles),
        sources=items,
        sentiment=sentiment,
    )


def scan_market_news(
    provider: ResearchProvider,
    candidate_symbols: List[str],
    max_shortlist: int,
    query_text: str = "NSE stocks India market today",
    per_symbol_news_limit: int = 3,
) -> List[ShortlistCandidate]:
    universe = [symbol.upper() for symbol in candidate_symbols]
    if not universe or max_shortlist <= 0:
        return []

    market_items: List[ResearchItem] = []
    search = getattr(provider, "search", None)
    if callable(search):
        try:
            market_items = search(query_text, symbol="MARKET", limit=20)
        except Exception:
            market_items = []

    scored: dict[str, dict[str, object]] = {
        symbol: {"score": 0.0, "sources": [], "titles": [], "mentions": 0, "items": []}
        for symbol in universe
    }
    for item in market_items:
        title_upper = item.title.upper()
        for symbol in universe:
            if symbol in title_upper:
                bucket = scored[symbol]
                bucket["score"] = float(bucket["score"]) + 2.0
                bucket["mentions"] = int(bucket["mentions"]) + 1
                cast_sources = bucket["sources"]
                cast_titles = bucket["titles"]
                cast_items = bucket["items"]
                if isinstance(cast_sources, list):
                    cast_sources.append(item.url)
                if isinstance(cast_titles, list):
                    cast_titles.append(item.title)
                if isinstance(cast_items, list):
                    cast_items.append(item)

    for index, symbol in enumerate(universe):
        try:
            items = provider.fetch(symbol)[:per_symbol_news_limit]
        except Exception:
            items = []
        if not items:
            continue
        bucket = scored[symbol]
        bucket["score"] = float(bucket["score"]) + max(0.1, per_symbol_news_limit - index * 0.01)
        cast_sources = bucket["sources"]
        cast_titles = bucket["titles"]
        cast_items = bucket["items"]
        if isinstance(cast_sources, list):
            cast_sources.extend(item.url for item in items)
        if isinstance(cast_titles, list):
            cast_titles.extend(item.title for item in items)
        if isinstance(cast_items, list):
            cast_items.extend(items)

    candidates: List[ShortlistCandidate] = []
    for symbol, bucket in scored.items():
        if float(bucket["score"]) <= 0:
            continue
        items = bucket["items"] if isinstance(bucket["items"], list) else []
        titles = bucket["titles"] if isinstance(bucket["titles"], list) else []
        sources = bucket["sources"] if isinstance(bucket["sources"], list) else []
        sentiment = summarize_research(symbol, items).sentiment if items else "neutral"
        reason = "; ".join(str(title) for title in titles[:3]) or "Symbol appeared in configured discovery universe."
        candidates.append(
            ShortlistCandidate(
                symbol=symbol,
                score=round(float(bucket["score"]), 4),
                reason=reason,
                sources=list(dict.fromkeys(str(source) for source in sources))[:5],
                sentiment=sentiment,
                mentions=int(bucket["mentions"]),
            )
        )

    if not candidates:
        return [
            ShortlistCandidate(
                symbol=symbol,
                score=0.0,
                reason="Fallback from configured Indian-market seed universe.",
                sources=[],
                sentiment="neutral",
                mentions=0,
            )
            for symbol in universe[:max_shortlist]
        ]

    candidates.sort(key=lambda candidate: (-candidate.score, universe.index(candidate.symbol)))
    return candidates[:max_shortlist]
