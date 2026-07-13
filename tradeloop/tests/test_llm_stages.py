import json

import pytest

from tradeloop.lib.llm import stages
from tradeloop.lib.llm.schemas import Shortlist


class FakeClient:
    def __init__(self, obj, fail_first=False):
        self.obj = obj
        self.fail_first = fail_first
        self.calls = 0

    def call_json(self, role, system, user, schema, model=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            from tradeloop.lib.llm.client import LLMValidationError
            raise LLMValidationError("bad once")
        return schema.model_validate(self.obj)


def _run_dir(tmp_path):
    d = tmp_path / "runs" / "2026-07-02_0800_premarket"
    d.mkdir(parents=True)
    (d / "10_news.md").write_text("# news\nRELIANCE earnings beat\n")
    (d / "11_sentiment.md").write_text("# sentiment\n")
    (d / "12_fundamentals.md").write_text("# fundamentals\n")
    (d / "13_technical.md").write_text("# technical\n")
    return d


GOOD_SHORTLIST = {
    "candidates": [{
        "ticker": "RELIANCE", "catalyst_type": "earnings", "source_track": "tier_a",
        "composite_score": 7.5, "thesis": "beat", "horizon": "5-20 days",
        "evidence": ["a1b2c3d4e5f6"],
    }],
    "evidence": ["a1b2c3d4e5f6"],
}


def test_dag_has_thirteen_roles_in_order():
    assert stages.DAG[0] == "10_news"
    assert stages.DAG.index("30_trade_plan") < stages.DAG.index("41_pm_decision")
    assert "41_pm_decision" in stages.DAG


def test_run_stage_writes_validated_artifact(tmp_path):
    d = _run_dir(tmp_path)
    client = FakeClient(GOOD_SHORTLIST)
    out = stages.run_stage("14_shortlist", d, client)
    assert isinstance(out, Shortlist)
    saved = json.loads((d / "14_shortlist.json").read_text())
    assert saved["candidates"][0]["ticker"] == "RELIANCE"
    assert (d / "14_shortlist.md").exists()


def test_run_stage_retries_once_on_invalid(tmp_path):
    d = _run_dir(tmp_path)
    client = FakeClient(GOOD_SHORTLIST, fail_first=True)
    out = stages.run_stage("14_shortlist", d, client)
    assert isinstance(out, Shortlist)
    assert client.calls == 2


def test_run_stage_missing_prompt_raises(tmp_path):
    d = _run_dir(tmp_path)
    with pytest.raises(FileNotFoundError):
        stages.run_stage("99_nope", d, FakeClient(GOOD_SHORTLIST))


def test_holdings_review_stage_wired(tmp_path):
    from tradeloop.lib.llm import stages, schemas

    class FakeClient:
        def call_json(self, role, system, user, schema, model=None):
            assert role == "15_holdings_review"
            assert schema is schemas.HoldingsReview
            assert "00_context.md" in user           # named inputs assembled
            return schemas.HoldingsReview(reviews=[], carry_forward="nothing to flag")

    (tmp_path / "00_context.md").write_text("# ctx\n", encoding="utf-8")
    out = stages.run_stage("15_holdings_review", tmp_path, FakeClient())
    assert out.carry_forward == "nothing to flag"
    assert (tmp_path / "15_holdings_review.json").exists()
    assert (tmp_path / "15_holdings_review.md").exists()


def test_holdings_review_prompt_file_exists():
    from tradeloop.lib.llm.stages import PROMPTS_DIR, PROMPT_PATH
    assert (PROMPTS_DIR / f"{PROMPT_PATH['15_holdings_review']}.md").exists()
