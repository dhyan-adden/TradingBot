from __future__ import annotations

import re

# ponytail: lexicon+negation baseline; the P1 LLM does nuanced per-name sentiment.
POSITIVE = {"strong", "bullish", "growth", "profit", "beat", "up", "rally", "surge",
            "record", "wins", "gain", "upgrade", "outperform"}
NEGATIVE = {"weak", "bearish", "fall", "fraud", "loss", "down", "probe", "penalty",
            "miss", "cut", "downgrade", "default", "resigns"}
NEGATORS = {"no", "not", "never", "without", "fails", "failed"}


def score(text: str) -> float:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return 0.0
    raw = 0
    for i, tok in enumerate(tokens):
        negated = i > 0 and tokens[i - 1] in NEGATORS
        if tok in POSITIVE:
            raw += -1 if negated else 1
        elif tok in NEGATIVE:
            raw += 1 if negated else -1
    # normalise by a soft cap so a few strong terms saturate toward +/-1.
    return max(-1.0, min(1.0, raw / 3.0))


def label(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
