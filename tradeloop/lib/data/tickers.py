from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.ticker_master import TickerMaster

MIN_ALIAS_LEN = 3

CATEGORY_TERMS = {
    "earnings": ["profit", "quarter", "results", "earnings"],
    "order_win": ["order", "contract", "deal", "wins"],
    "regulatory": ["sebi", "penalty", "probe", "regulator"],
    "macro": ["rbi", "inflation", "oil", "rupee", "fed"],
    "m&a": ["acquire", "merger", "stake", "buyout"],
    "management": ["ceo", "cfo", "resigns", "appoints"],
}


@dataclass(frozen=True)
class TaggedStory:
    ticker: str
    title: str
    url: str
    source: str
    tier: str
    category: str
    news_id: str
    confidence: float


def categorize(title: str) -> str:
    lowered = title.lower()
    for category, terms in CATEGORY_TERMS.items():
        if any(term in lowered for term in terms):
            return category
    return "other"


def extract(items: Iterable[RawItem], master: TickerMaster) -> List[TaggedStory]:
    amap = master.alias_map()
    # Pre-compile one word-boundary pattern per alias >= MIN_ALIAS_LEN.
    patterns = [
        (re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), record.symbol)
        for alias, record in amap.items()
        if len(alias) >= MIN_ALIAS_LEN
    ]
    tagged: List[TaggedStory] = []
    for item in items:
        matched: set[str] = set()
        for pattern, symbol in patterns:
            if symbol in matched:
                continue
            if pattern.search(item.title):
                matched.add(symbol)
        category = categorize(item.title)
        for symbol in sorted(matched):
            tagged.append(
                TaggedStory(
                    ticker=symbol,
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    tier=item.tier,
                    category=category,
                    news_id=item.news_id,
                    confidence=1.0,
                )
            )
    return tagged
