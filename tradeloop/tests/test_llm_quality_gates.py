"""Phase 5: analyst output quality gates.

Weak small-model output degrades safely (logged to analysis_quality.jsonl) and
a hard_block/new_buys line forbids new BUY entries before approval - never
silently becoming a confident trade.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.llm.quality import (
    LLMValidationError,
    quality_has_hard_block_new_buys,
    validate_stage_quality,
)
from tradeloop.lib.llm.schemas import (
    NewsAnalysis,
    NewsName,
    SCHEMA_FOR_STAGE,
    Shortlist,
    ShortlistCandidate,
)
from tradeloop.lib.llm.stages import STAGE_INPUTS

import pytest


def test_news_tier_a_without_evidence_flagged(tmp_path):
    res = NewsAnalysis(names_in_play=[
        NewsName(ticker="RELIANCE", catalyst="earnings", tier="A", evidence=[])])
    validate_stage_quality("10_news", res, tmp_path)
    lines = [json.loads(l) for l in (tmp_path / "analysis_quality.jsonl").read_text().splitlines()]
    assert any(l["stage"] == "10_news" and l["severity"] == "degraded"
               and l["scope"] == "research_only" for l in lines)


def test_shortlist_news_driven_without_evidence_flagged(tmp_path):
    res = Shortlist(candidates=[
        ShortlistCandidate(ticker="RELIANCE", catalyst_type="earnings",
                           source_track="tier_a", thesis="x",
                           composite_score=5.0, horizon="1-5 days", evidence=[])])
    validate_stage_quality("14_shortlist", res, tmp_path)
    lines = [json.loads(l) for l in (tmp_path / "analysis_quality.jsonl").read_text().splitlines()]
    assert any(l["stage"] == "14_shortlist" and l["severity"] == "degraded"
               and l["scope"] == "research_only" for l in lines)


def test_non_pm_stage_cannot_emit_orders(tmp_path):
    class FakeOrders(BaseModel):
        orders: list = []

    with pytest.raises(LLMValidationError):
        validate_stage_quality("10_news", FakeOrders(orders=[{"side": "BUY"}]), tmp_path)


def test_only_pm_schema_carries_orders():
    for stage, schema in SCHEMA_FOR_STAGE.items():
        has_orders = "orders" in schema.model_fields
        assert has_orders == (stage == "41_pm_decision"), stage


def test_quality_jsonl_in_manager_stage_inputs():
    for stage in ["22_debate", "30_trade_plan", "40_risk_report", "41_pm_decision"]:
        assert "analysis_quality.jsonl" in STAGE_INPUTS[stage]


def _writes_hard_block_new_buys(run_dir: Path) -> None:
    (run_dir / "analysis_quality.jsonl").write_text(json.dumps(
        {"stage": "10_news", "severity": "hard_block", "scope": "new_buys",
         "reason": "r", "created_at": "t"}) + "\n", encoding="utf-8")


def _would_block_buy(run_dir: Path) -> bool:
    # Mirrors orchestrator.run_cycle's pre-approval quality gate exactly.
    if not quality_has_hard_block_new_buys(run_dir):
        return False
    return any(str(o.side).upper() == "BUY"
               for o in load_orders(run_dir / "orders.json").orders)


def test_hard_block_new_buys_prevents_buy(tmp_path):
    _writes_hard_block_new_buys(tmp_path)
    (tmp_path / "orders.json").write_text(json.dumps(
        {"orders": [{"ticker": "X", "side": "BUY", "quantity": 1, "price": 1.0}]}),
        encoding="utf-8")
    assert _would_block_buy(tmp_path) is True


def test_hard_block_new_buys_allows_sell_only_exit(tmp_path):
    _writes_hard_block_new_buys(tmp_path)
    (tmp_path / "orders.json").write_text(json.dumps(
        {"orders": [{"ticker": "X", "side": "SELL", "quantity": 1, "price": 1.0}]}),
        encoding="utf-8")
    assert _would_block_buy(tmp_path) is False
