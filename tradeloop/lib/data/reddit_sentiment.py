from dataclasses import dataclass
from typing import Iterable, List


POSITIVE_TERMS = {"breakout", "strong", "bullish", "growth", "profit", "up", "beat"}
NEGATIVE_TERMS = {"weak", "fall", "fraud", "loss", "bearish", "down", "probe"}


@dataclass(frozen=True)
class SentimentScore:
    symbol: str
    score: float
    label: str
    positives: int
    negatives: int


def score_texts(symbol: str, texts: Iterable[str]) -> SentimentScore:
    lowered = " ".join(texts).lower()
    positives = sum(1 for term in POSITIVE_TERMS if term in lowered)
    negatives = sum(1 for term in NEGATIVE_TERMS if term in lowered)
    score = positives - negatives
    label = "neutral"
    if score > 0:
        label = "positive"
    elif score < 0:
        label = "negative"
    return SentimentScore(symbol=symbol.strip().upper(), score=float(score), label=label, positives=positives, negatives=negatives)


def fetch_reddit_sentiment(symbol: str) -> SentimentScore:
    """Placeholder for Reddit collection.

    Network/API access is intentionally not embedded in v1; Codex can paste
    public observations into run artifacts and this scorer can evaluate text.
    """

    return score_texts(symbol, [])

