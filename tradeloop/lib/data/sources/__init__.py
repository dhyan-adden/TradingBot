from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawItem:
    news_id: str
    title: str
    url: str
    source: str
    tier: str
    published_at: str
    body: str = ""
