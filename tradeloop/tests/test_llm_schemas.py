import pytest
from pydantic import ValidationError

from tradeloop.lib.llm import schemas


def test_every_dag_stage_has_a_schema():
    for stage in schemas.SCHEMA_FOR_STAGE:
        assert issubclass(schemas.SCHEMA_FOR_STAGE[stage], schemas.BaseModel)
    # decision + research stages must carry the evidence trailer
    for stage in ("20_bull", "21_bear", "30_trade_plan", "41_pm_decision"):
        model = schemas.SCHEMA_FOR_STAGE[stage]
        assert "evidence" in model.model_fields, f"{stage} missing evidence trailer"


def test_evidence_filters_prose_keeps_only_news_ids():
    # Live smoke showed models stuff prose rationales into evidence; the P3 gate
    # must judge real news_id citations, not sentences. The filter keeps 12-hex
    # ids and drops prose / wrong-length / uppercase. A fabricated-but-well-formed
    # id is KEPT on purpose so the evidence gate can still catch it downstream.
    sr = schemas.SentimentReport.model_validate({
        "scores": [],
        "evidence": ["a1b2c3d4e5f6", "Banks in focus ahead of Q1 results",
                     "deadbeefcafe", "A1B2C3D4E5F6", "short", "a1b2c3d4e5f"],
    })
    assert sr.evidence == ["a1b2c3d4e5f6", "deadbeefcafe"]


def test_shortlist_candidate_valid():
    sl = schemas.Shortlist.model_validate({
        "candidates": [{
            "ticker": "RELIANCE", "catalyst_type": "earnings",
            "source_track": "tier_a", "composite_score": 7.5,
            "thesis": "beat + guidance raise", "horizon": "5-20 days",
            "evidence": ["a1b2c3d4e5f6"],
        }],
        "evidence": ["a1b2c3d4e5f6"],
    })
    assert sl.candidates[0].ticker == "RELIANCE"


def test_debate_verdict_enum_enforced():
    with pytest.raises(ValidationError):
        schemas.Debate.model_validate({
            "names": [{"ticker": "TCS", "conviction": 6.0, "verdict": "maybe",
                       "evidence": ["x"]}],
            "evidence": ["x"],
        })


def test_trade_plan_is_long_only():
    with pytest.raises(ValidationError):
        schemas.TradePlan.model_validate({
            "tickets": [{
                "ticker": "TCS", "side": "SHORT", "product": "CNC",
                "strategy_family": "breakout", "entry": 100.0, "hard_stop": 95.0,
                "target_1": 110.0, "target_2": 120.0, "quantity": 5,
                "time_horizon": "5-20 days", "thesis": "x", "conviction": 7.0,
                "evidence": ["x"],
            }],
            "evidence": ["x"],
        })


def test_pm_decision_orders_match_order_shape():
    pm = schemas.PMDecision.model_validate({
        "orders": [{
            "ticker": "RELIANCE", "side": "BUY", "product": "CNC",
            "quantity": 8, "price": 2500.0, "order_type": "LIMIT",
            "hard_stop": 2425.0, "target_1": 2625.0, "target_2": 2750.0,
            "strategy_family": "breakout_20d_pullback", "reason": "approved",
        }],
        "held": [],
        "evidence": ["a1b2c3d4e5f6"],
    })
    assert pm.orders[0].side == "BUY"
    with pytest.raises(ValidationError):
        schemas.PMDecision.model_validate({
            "orders": [{"ticker": "X", "side": "BUY", "product": "CNC",
                        "quantity": -1, "price": 10.0}],
            "held": [], "evidence": [],
        })
