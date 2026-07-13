"""Pydantic output models for each stage of the 13-role DAG.

Every recommendation-bearing model carries an ``evidence: list[str]`` trailer of
news_ids (validated against the frozen snapshot in Phase 3). The trade-ticket and
PM-order models reuse the exact field shape of ``orders_schema.Order`` (P0 §5.2)
so Python - not the LLM - serialises orders.json from a validated object.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_NEWS_ID_RE = re.compile(r"^[0-9a-f]{12}$")


# --- shared trailer -------------------------------------------------------
class EvidenceMixin(BaseModel):
    evidence: list[str] = Field(
        default_factory=list,
        description="12-char hex news_id tokens copied verbatim from the input's "
                    "[news_id] brackets; omit if the claim rests on no news item.",
    )

    @field_validator("evidence")
    @classmethod
    def _only_news_ids(cls, value: list[str]) -> list[str]:
        # Models often stuff prose rationales into this field; keep only
        # well-formed news_ids so the P3 evidence gate judges real citations
        # (and catches fabricated ids), not sentences.
        return [s for s in value if isinstance(s, str) and _NEWS_ID_RE.match(s)]


# --- money-path order shape (mirrors orders_schema.Order, P0 §5.2) --------
class Order(BaseModel):
    ticker: str
    side: Literal["BUY", "SELL"]
    product: Literal["CNC", "MIS"] = "CNC"
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    order_type: str = "LIMIT"
    hard_stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    max_entry_price: float | None = None
    strategy_family: str | None = None
    status: str | None = None
    reason: str = ""


# --- 05 adhoc intake ------------------------------------------------------
class AdhocIntake(BaseModel):
    classification: Literal[
        "market_research", "ticker_dossier",
        "portfolio_management", "full_trade_request",
    ]
    safe_interpretation: str
    # Exact DAG artifact filenames (mirrors stages.DAG; a sync test enforces it).
    # Live 2026-07-13: an unconstrained list[str] let descriptive names through,
    # the pruning intersection went empty, and the whole cycle ran hollow.
    required_stages: list[Literal[
        "10_news.md", "11_sentiment.md", "12_fundamentals.md", "13_technical.md",
        "14_shortlist.md", "20_bull.md", "21_bear.md", "22_debate.md",
        "30_trade_plan.md", "40_risk_report.md", "41_pm_decision.md",
    ]] = Field(default_factory=list)
    refused_parts: list[str] = Field(default_factory=list)


# --- 10 news --------------------------------------------------------------
class NewsName(EvidenceMixin):
    ticker: str
    catalyst: str
    tier: Literal["A", "B", "C"]


class NewsAnalysis(EvidenceMixin):
    macro_context: str = ""
    names_in_play: list[NewsName] = Field(default_factory=list)
    macro_themes: list[str] = Field(default_factory=list)


# --- 11 sentiment ---------------------------------------------------------
class SentimentScore(BaseModel):
    ticker: str
    sentiment_score: float = Field(ge=-1, le=1)
    echo_chamber_flag: bool = False


class SentimentReport(EvidenceMixin):
    scores: list[SentimentScore] = Field(default_factory=list)


# --- 12 fundamentals ------------------------------------------------------
class FundamentalTag(EvidenceMixin):
    ticker: str
    tag: Literal["green", "yellow", "red"]
    red_flags: list[str] = Field(default_factory=list)


class FundamentalsReport(EvidenceMixin):
    tags: list[FundamentalTag] = Field(default_factory=list)


# --- 13 technical ---------------------------------------------------------
class TechnicalSetup(EvidenceMixin):
    ticker: str
    classification: Literal[
        "bullish_entry", "bullish_continuation", "exit_watch", "avoid",
    ]
    news_confirmed: bool = False
    notes: str = ""


class TechnicalReport(EvidenceMixin):
    setups: list[TechnicalSetup] = Field(default_factory=list)


# --- 14 shortlist ---------------------------------------------------------
class ShortlistCandidate(EvidenceMixin):
    ticker: str
    catalyst_type: str
    source_track: Literal["tier_a", "tier_b", "tier_c", "quiet"]
    composite_score: float = Field(ge=0, le=10)
    thesis: str
    horizon: Literal["1-5 days", "5-20 days"]  # intraday-only dropped: swing, long-only


class Shortlist(EvidenceMixin):
    candidates: list[ShortlistCandidate] = Field(default_factory=list)


# --- 20/21 bull & bear ----------------------------------------------------
class Argument(EvidenceMixin):
    ticker: str
    claim: str


class BullCase(EvidenceMixin):
    arguments: list[Argument] = Field(default_factory=list)


class BearCase(EvidenceMixin):
    arguments: list[Argument] = Field(default_factory=list)
    tier_c_only: list[str] = Field(default_factory=list)
    pump_risk: list[str] = Field(default_factory=list)


# --- 22 debate ------------------------------------------------------------
class DebateVerdict(EvidenceMixin):
    ticker: str
    conviction: float = Field(ge=0, le=10)
    verdict: Literal["tradeable", "watch", "pass"]
    rationale: str = Field(
        default="",  # pre-rationale run archives must keep validating
        description="One sentence naming the decisive bull or bear point that "
                    "set this verdict.",
    )


class Debate(EvidenceMixin):
    names: list[DebateVerdict] = Field(default_factory=list)


# --- 15 holdings review (non-order modes only) ------------------------------
class HoldingVerdict(EvidenceMixin):
    ticker: str
    verdict: Literal["HOLD", "ADD", "TIGHTEN_STOP", "TRIM", "EXIT"]
    conviction: float = Field(ge=0, le=10)
    # Exits are reason-coded, never P&L-impulse: cutting winners early because
    # they are green is how swing expectancy dies (profit_protect -> tighten, not exit).
    reason_code: Literal[
        "stop_breach", "tripwire", "thesis_break", "event_risk",
        "profit_protect", "thesis_intact", "thesis_strengthened",
    ]
    rationale: str = ""
    new_stop: float | None = Field(default=None, gt=0)
    exit_quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _verdict_requires_params(self):
        if self.verdict == "TIGHTEN_STOP" and self.new_stop is None:
            raise ValueError("TIGHTEN_STOP requires new_stop")
        if self.verdict == "TRIM" and self.exit_quantity is None:
            raise ValueError("TRIM requires exit_quantity")
        return self


class HoldingsReview(EvidenceMixin):
    reviews: list[HoldingVerdict] = Field(default_factory=list)
    carry_forward: str = ""


# --- 30 trade plan (unified Trade Ticket) ---------------------------------
class TradeTicket(EvidenceMixin):
    ticker: str
    side: Literal["BUY", "SELL"]           # long-only: SELL is exit-only
    product: Literal["CNC", "MIS"] = "CNC"
    strategy_family: str
    entry: float = Field(gt=0)
    hard_stop: float = Field(gt=0)
    target_1: float
    target_2: float
    quantity: int = Field(gt=0)
    time_horizon: str
    thesis: str
    conviction: float = Field(ge=0, le=10)


class TradePlan(EvidenceMixin):
    tickets: list[TradeTicket] = Field(default_factory=list)


# --- 40 risk report -------------------------------------------------------
class RiskDecisionRow(BaseModel):
    ticker: str
    decision: Literal["approve", "resize", "reject"]
    resized_quantity: int | None = None
    reasons: list[str] = Field(default_factory=list)


class RiskReport(EvidenceMixin):
    decisions: list[RiskDecisionRow] = Field(default_factory=list)


# --- 41 PM decision (Python serialises orders.json from this) --------------
class PMDecision(EvidenceMixin):
    orders: list[Order] = Field(default_factory=list)
    held: list[Order] = Field(default_factory=list)


# --- 50 post trade --------------------------------------------------------
class Outcome(BaseModel):
    ticker: str
    outcome: Literal[
        "thesis_correct_won", "thesis_correct_stopped",
        "thesis_wrong_won", "thesis_wrong_lost",
    ]
    lesson: str = ""


class PostTradeReport(BaseModel):
    outcomes: list[Outcome] = Field(default_factory=list)
    strategy_updates: dict[str, str] = Field(default_factory=dict)


SCHEMA_FOR_STAGE: dict[str, type[BaseModel]] = {
    "05_adhoc_intake": AdhocIntake,
    "10_news": NewsAnalysis,
    "11_sentiment": SentimentReport,
    "12_fundamentals": FundamentalsReport,
    "13_technical": TechnicalReport,
    "14_shortlist": Shortlist,
    "15_holdings_review": HoldingsReview,
    "20_bull": BullCase,
    "21_bear": BearCase,
    "22_debate": Debate,
    "30_trade_plan": TradePlan,
    "40_risk_report": RiskReport,
    "41_pm_decision": PMDecision,
    "50_post_trade": PostTradeReport,
}
