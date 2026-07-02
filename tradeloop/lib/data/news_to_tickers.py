from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from tradeloop.lib.data.google_news_rss import NewsItem
from tradeloop.lib.data.ticker_master import TickerRecord, alias_index


@dataclass(frozen=True)
class TaggedStory:
    ticker: str
    title: str
    url: str
    source: str
    tier: str
    category: str
    confidence: float


@dataclass(frozen=True)
class NewsExtraction:
    by_ticker: Dict[str, List[TaggedStory]] = field(default_factory=dict)
    macro: List[NewsItem] = field(default_factory=list)


MACRO_TERMS = {"RBI", "INR", "RUPEE", "OIL", "FED", "FII", "DII", "INFLATION", "GDP"}
CATEGORY_TERMS = {
    "earnings": ["profit", "quarter", "results", "earnings"],
    "order_win": ["order", "contract", "deal", "wins"],
    "regulatory": ["sebi", "rbi", "penalty", "probe", "regulator"],
    "macro": ["rbi", "inflation", "oil", "rupee", "fed"],
    "m&a": ["acquire", "merger", "stake", "buyout"],
    "management": ["ceo", "cfo", "resigns", "appoints"],
}


def extract_tickers(items: Iterable[NewsItem], records: Iterable[TickerRecord], source_tiers: Dict[str, str]) -> NewsExtraction:
    index = alias_index(records)
    by_ticker: Dict[str, List[TaggedStory]] = {}
    macro: List[NewsItem] = []
    for item in items:
        title_upper = item.title.upper()
        if any(term in title_upper for term in MACRO_TERMS):
            macro.append(item)
        matched: set[str] = set()
        for alias, record in index.items():
            if alias and alias in title_upper:
                matched.add(record.symbol)
        for symbol in matched:
            by_ticker.setdefault(symbol, []).append(
                TaggedStory(
                    ticker=symbol,
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    tier=source_tiers.get(item.source, "tier_C"),
                    category=categorize(item.title),
                    confidence=1.0,
                )
            )
    return NewsExtraction(by_ticker=by_ticker, macro=macro)


def categorize(title: str) -> str:
    lowered = title.lower()
    for category, terms in CATEGORY_TERMS.items():
        if any(term in lowered for term in terms):
            return category
    return "other"


def render_news_raw(extraction: NewsExtraction) -> str:
    lines = ["# Raw News", "", "## Macro Stories"]
    for item in extraction.macro:
        lines.append(f"- {item.title} ({item.source}) {item.url}")
    lines.extend(["", "## Ticker Stories"])
    for ticker, stories in sorted(extraction.by_ticker.items()):
        lines.append(f"### {ticker}")
        for story in stories:
            lines.append(f"- [{story.tier}] {story.category}: {story.title} ({story.source}) {story.url}")
    lines.append("")
    return "\n".join(lines)

