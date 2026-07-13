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


def test_adhoc_required_stages_rejects_descriptive_names():
    # live 2026-07-13_1246_adhoc: the intake returned descriptive names like
    # "news_catalyst_research"; the unconstrained list[str] validated, the DAG
    # pruning intersection went empty, and the cycle completed hollow
    with pytest.raises(ValidationError):
        schemas.AdhocIntake.model_validate({
            "classification": "full_trade_request", "safe_interpretation": "x",
            "required_stages": ["news_catalyst_research", "bull_vs_bear_debate"],
        })


def test_adhoc_required_stages_accepts_real_artifact_names():
    intake = schemas.AdhocIntake.model_validate({
        "classification": "ticker_dossier", "safe_interpretation": "x",
        "required_stages": ["10_news.md", "13_technical.md", "22_debate.md"],
    })
    assert intake.required_stages == ["10_news.md", "13_technical.md", "22_debate.md"]


def test_adhoc_required_stages_literal_stays_in_sync_with_dag():
    from typing import get_args
    from tradeloop.lib.llm import stages
    literal = get_args(schemas.AdhocIntake.model_fields["required_stages"].annotation)[0]
    assert set(get_args(literal)) == {f"{s}.md" for s in stages.DAG}


def test_debate_verdict_rationale_defaults_empty_for_legacy_payloads():
    # pre-rationale archives (and a model that omits it) must still validate
    d = schemas.Debate.model_validate({
        "names": [{"ticker": "TCS", "conviction": 6.0, "verdict": "watch"}]})
    assert d.names[0].rationale == ""
    d = schemas.Debate.model_validate({
        "names": [{"ticker": "TCS", "conviction": 6.0, "verdict": "watch",
                   "rationale": "bear case decisive"}]})
    assert d.names[0].rationale == "bear case decisive"


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
