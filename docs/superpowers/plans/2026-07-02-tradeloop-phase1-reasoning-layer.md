# TradeLoop Phase 1 — Reasoning Layer Implementation Plan

**Goal:** Python calls the models directly (OpenRouter), each of the 13 analyst stages fills in a validated pydantic form with an evidence trailer, and every call records model_version/response_id/prompt/response/token-usage — replacing the P0 orchestrator's `_run_reasoning()` external-CLI body with in-process per-stage calls.

> **2026-07-03 verification patch (before execution):**
> - Model slugs live-verified against `https://openrouter.ai/api/v1/models` (340 models). `anthropic/claude-haiku-4.5`, `claude-sonnet-4.5`, `claude-opus-4.5` all present and kept. `deepseek/deepseek-3.2` did **not** exist — corrected throughout to `deepseek/deepseek-v3.2` (the real stable slug). Newer tiers (`opus-4.8`, `sonnet-5`, `deepseek-v4-pro`) exist and are available if a future upgrade is wanted; the reviewed 4.5 tier stands for now.
> - Task 5 replaces `_run_reasoning`'s body, so it no longer spawns the `run_cycle.sh` subprocess. Three now-obsolete tests that assert that subprocess behavior must be **removed** as part of Task 5: `test_run_reasoning_pins_run_dir_env`, `test_run_reasoning_passes_agent_to_backend`, and the `--agent` CLI flag + `test_cli_agent_flag_selects_backend` (the flag becomes a no-op once reasoning is in-process; drop the flag from `main()` and revert it to `mode + --request`). `run_cycle.sh` stays on disk as legacy. Net suite after P1 must be green.

**Architecture:** A new `tradeloop/lib/llm/` package: `client.py` (OpenRouter POST with retry/backoff + full-provenance audit, reusing the proven transport in `src/tradingbot/llm.py`), `routing.py` (stage→real-model-ID table), `schemas.py` (pydantic output model per stage, each carrying `evidence: list[str]`), and `stages.py` (load the existing markdown prompt as the system prompt + named inputs from the run dir, call the model, validate against the schema with retry-on-invalid, write the stage artifact). The orchestrator's reasoning seam runs the 13-role DAG in-process; the deterministic P0 order path (`route_orders_file` → `evaluate()`) is untouched — Python still owns `orders.json` serialization and gating.

**Tech Stack:** Python 3.11, httpx (already a dep), pydantic v2 (already a dep), pytest with recorded fixtures (no live network in tests). OpenRouter chat-completions wire API (`response_format: {type: json_schema}` where honored; brace-balanced JSON extraction as the universal fallback).

## Global Constraints

- India cash equities only (segment EQ); no other exchange/instrument.
- Long-only: BUY opens/adds, SELL exits only; no shorts, no F&O, no NRML, no leverage.
- Products: CNC or MIS only.
- `tradeloop/kill_switch.md` present → cycle halts, no orders (enforced by orchestrator gate in P0; reasoning layer never routes).
- Paper default: `ZERODHA_ENABLE_TRADING=false` (settings.yaml `trading.zerodha_enable_trading`).
- Live only past the promotion gate (`settings.yaml live_promotion_gates`: min_paper_trades=40, min_win_rate=0.45, min_expectancy_r=0.3, max_drawdown_pct=8).
- The risk gate `checks.evaluate()` runs on every order (P0 order path — unchanged by Phase 1).
- Security (AGENTS.md): never read/print `.env`; never log values whose name contains KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL. The only sanctioned secret read is `OPENROUTER_API_KEY` via `os.getenv`, never echoed.

## File Structure

| File | Responsibility |
|---|---|
| `tradeloop/lib/llm/__init__.py` | Package marker (new). |
| `tradeloop/lib/llm/routing.py` | `STAGE_MODELS` table mapping each stage name → real OpenRouter model ID; `model_for(stage)`. |
| `tradeloop/lib/llm/schemas.py` | One pydantic output model per stage, each with an `evidence: list[str]` trailer; `SCHEMA_FOR_STAGE` registry. |
| `tradeloop/lib/llm/client.py` | `LLMClient.call_json(role, system, user, schema)` → validated `BaseModel`; OpenRouter POST with retry/backoff, full provenance record (`CallRecord`), append to `llm_calls.jsonl` audit. |
| `tradeloop/lib/llm/stages.py` | `run_stage(name, run_dir)`: load markdown prompt + named inputs, call client, validate (retry on invalid), write stage artifact; `STAGE_INPUTS` map; `DAG` order. |
| `tradeloop/orchestrator.py` (modify) | Replace `_run_reasoning()` body: run the DAG via `stages.run_stage` in-process instead of exec-ing the external CLI. |
| `tradeloop/prompts/shared/model_routing.md` (modify) | Replace the fake OpenRouter model IDs with the real ones now in `routing.py`. |
| `tradeloop/tests/test_llm_client.py` | Client: retry/backoff, provenance capture, schema validation + retry, fallback. |
| `tradeloop/tests/test_llm_schemas.py` | Each stage schema validates a good doc and rejects a bad one; evidence trailer present. |
| `tradeloop/tests/test_llm_stages.py` | `run_stage` loads prompt+inputs, validates, writes artifact; retries once on invalid then raises. |
| `tradeloop/tests/fixtures/or_*.json` | Recorded OpenRouter response bodies used by tests (no live net). |

---

### Task 1: `routing.py` — stage→model table with real OpenRouter IDs

**Files**
- create `tradeloop/lib/llm/__init__.py`
- create `tradeloop/lib/llm/routing.py`
- create `tradeloop/tests/test_llm_routing.py`

**Interfaces**
- Produces: `STAGE_MODELS: dict[str, str]`; `model_for(stage: str) -> str`; `DEFAULT_MODEL: str`.

Real OpenRouter slugs (confirmed via OpenRouter docs, 2026-07-02): tier intent haiku=classify, sonnet=analysis, opus=decisions →
`anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.5`, `anthropic/claude-opus-4.5`, plus `deepseek/deepseek-v3.2` for the two news/technical analysis stages (kept as a cheaper analysis tier, matching the old deepseek assignment intent). Stage keys are the artifact base names used everywhere else in the tree (`10_news`, `30_trade_plan`, …).

**Steps**

1. Write failing test:

```python
# tradeloop/tests/test_llm_routing.py
from tradeloop.lib.llm import routing


def test_every_dag_stage_has_a_real_model():
    stages = [
        "05_adhoc_intake", "10_news", "11_sentiment", "12_fundamentals",
        "13_technical", "14_shortlist", "20_bull", "21_bear", "22_debate",
        "30_trade_plan", "40_risk_report", "41_pm_decision", "50_post_trade",
    ]
    for s in stages:
        model = routing.model_for(s)
        assert "/" in model, f"{s} -> {model!r} is not an org/model slug"
        assert "minimax" not in model and "mimo" not in model and "hy3" not in model, \
            f"{s} still points at a fake placeholder model {model!r}"


def test_decision_stages_use_opus():
    for s in ("22_debate", "30_trade_plan", "40_risk_report", "41_pm_decision"):
        assert routing.model_for(s) == "anthropic/claude-opus-4.5"


def test_classify_stages_use_haiku():
    for s in ("05_adhoc_intake", "11_sentiment"):
        assert routing.model_for(s) == "anthropic/claude-haiku-4.5"


def test_unknown_stage_falls_back_to_default():
    assert routing.model_for("99_unknown") == routing.DEFAULT_MODEL
```

2. Run it (expect FAIL — module does not exist):
```
python -m pytest tradeloop/tests/test_llm_routing.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.llm.routing'`.

3. Minimal implementation:

```python
# tradeloop/lib/llm/__init__.py
```
(empty file)

```python
# tradeloop/lib/llm/routing.py
"""Stage -> OpenRouter model routing for the 13-role DAG.

Tier intent (from prompts/shared/model_routing.md): haiku=classify,
sonnet=analysis, opus=high-stakes decisions. The prior OpenRouter IDs
(minimax/mimo/hy3/deepseek-v4-flash) were placeholders that do not exist on
the provider; these are real current slugs.
"""
from __future__ import annotations

HAIKU = "anthropic/claude-haiku-4.5"     # light classification / sentiment
SONNET = "anthropic/claude-sonnet-4.5"   # analysis / research
OPUS = "anthropic/claude-opus-4.5"       # debate / trade / risk / PM decisions
DEEPSEEK = "deepseek/deepseek-v3.2"       # cheaper analysis tier (news/technical)

DEFAULT_MODEL = SONNET

STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": HAIKU,
    "10_news": DEEPSEEK,
    "11_sentiment": HAIKU,
    "12_fundamentals": SONNET,
    "13_technical": DEEPSEEK,
    "14_shortlist": SONNET,
    "20_bull": SONNET,
    "21_bear": SONNET,
    "22_debate": OPUS,
    "30_trade_plan": OPUS,
    "40_risk_report": OPUS,
    "41_pm_decision": OPUS,
    "50_post_trade": SONNET,
}


def model_for(stage: str) -> str:
    return STAGE_MODELS.get(stage, DEFAULT_MODEL)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_llm_routing.py -q
```
Expected: `4 passed`.

5. Commit:
```
git add tradeloop/lib/llm/__init__.py tradeloop/lib/llm/routing.py tradeloop/tests/test_llm_routing.py
git commit -m "P1: stage->model routing table with real OpenRouter IDs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `schemas.py` — per-stage pydantic outputs + evidence trailer

**Files**
- create `tradeloop/lib/llm/schemas.py`
- create `tradeloop/tests/test_llm_schemas.py`

**Interfaces**
- Consumes: `Order`/`OrdersFile` field shape from §5.2 of the P0 spec (`ticker`, `side` Literal["BUY","SELL"], `product` Literal["CNC","MIS"], `quantity`, `price`, `hard_stop`, `target_1`, `target_2`, `strategy_family`, `reason`) — the `41_pm_decision` schema reuses this exact shape so Python can serialize `orders.json` from it.
- Produces: `EvidenceTrailer` mixin field `evidence: list[str]`; stage models `AdhocIntake`, `NewsAnalysis`, `SentimentReport`, `FundamentalsReport`, `TechnicalReport`, `Shortlist`, `BullCase`, `BearCase`, `Debate`, `TradePlan`, `RiskReport`, `PMDecision`, `PostTradeReport`; `SCHEMA_FOR_STAGE: dict[str, type[BaseModel]]`.

The trade-ticket model unifies `30_trader.md`'s prose field list with `output_schemas.md`'s Trade Ticket JSON: `ticker, side, product, strategy_family, entry, hard_stop, target_1, target_2, quantity, time_horizon, thesis` + `conviction` (0-10, from the debate handoff) + `evidence`. Debate carries `{conviction, verdict}` (verdict Literal["tradeable","watch","pass"]) per `22_debate_moderator.md`. The PM decision carries the unified `orders: list[Order]` (same field shape as P0 `orders_schema.Order`) so `41_pm_decision` output is what Python later writes to `orders.json` — no LLM JSON authoring.

**Steps**

1. Write failing test:

```python
# tradeloop/tests/test_llm_schemas.py
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
```

2. Run it (expect FAIL):
```
python -m pytest tradeloop/tests/test_llm_schemas.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.llm.schemas'`.

3. Minimal implementation:

```python
# tradeloop/lib/llm/schemas.py
"""Pydantic output models for each stage of the 13-role DAG.

Every recommendation-bearing model carries an ``evidence: list[str]`` trailer of
news_ids (validated against the frozen snapshot in Phase 3). The trade-ticket and
PM-order models reuse the exact field shape of ``orders_schema.Order`` (P0 §5.2)
so Python — not the LLM — serialises orders.json from a validated object.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# --- shared trailer -------------------------------------------------------
class EvidenceMixin(BaseModel):
    evidence: list[str] = Field(default_factory=list)  # news_ids, checked in P3


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
    required_stages: list[str] = Field(default_factory=list)
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


class Debate(EvidenceMixin):
    names: list[DebateVerdict] = Field(default_factory=list)


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
    "20_bull": BullCase,
    "21_bear": BearCase,
    "22_debate": Debate,
    "30_trade_plan": TradePlan,
    "40_risk_report": RiskReport,
    "41_pm_decision": PMDecision,
    "50_post_trade": PostTradeReport,
}
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_llm_schemas.py -q
```
Expected: `5 passed`.

5. Commit:
```
git add tradeloop/lib/llm/schemas.py tradeloop/tests/test_llm_schemas.py
git commit -m "P1: per-stage pydantic output schemas with evidence trailer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `client.py` — OpenRouter call with retry/backoff + full provenance

**Files**
- create `tradeloop/lib/llm/client.py`
- create `tradeloop/tests/test_llm_client.py`
- create `tradeloop/tests/fixtures/or_ok_shortlist.json`
- create `tradeloop/tests/fixtures/or_bad_json.json`

**Interfaces**
- Consumes: `schemas.Shortlist` (test only); `routing.model_for` (not required here — the model is passed in by `stages`).
- Produces: `CallRecord` dataclass (`role, model, model_version, response_id, prompt, response, prompt_tokens, completion_tokens, total_tokens, used_model, reason`); `LLMClient(audit_path, api_key_env="OPENROUTER_API_KEY", base_url=..., max_tokens=4000, max_retries=3, timeout_seconds=60)`; `LLMClient.call_json(role: str, system: str, user: str, schema: type[BaseModel]) -> BaseModel` (matches §6 signature). Each call appends one `CallRecord` (as JSON) to the audit file — this is the input-reproducibility half of DoD #3.

Transport reuses the proven pattern from `src/tradingbot/llm.py`: JSON-only system prompt, `_extract_output_text` (str or list-of-parts), `_parse_json_object` with `_first_json_object` brace-balanced extraction (reasoning models emit the object twice). Additions: exponential backoff retry on transport errors, `response_format={"type":"json_schema", ...}` from the pydantic schema (honored by providers that support it; extraction is the universal fallback), pydantic validation, and capture of `body["id"]` (response_id), `body["model"]` (model_version) and `body["usage"]`.

**Steps**

1. Create the two recorded fixtures:

```json
// tradeloop/tests/fixtures/or_ok_shortlist.json
{
  "id": "gen-abc123",
  "model": "anthropic/claude-sonnet-4.5",
  "object": "chat.completion",
  "choices": [
    {
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "{\"candidates\":[{\"ticker\":\"RELIANCE\",\"catalyst_type\":\"earnings\",\"source_track\":\"tier_a\",\"composite_score\":7.5,\"thesis\":\"beat\",\"horizon\":\"5-20 days\",\"evidence\":[\"a1b2c3d4e5f6\"]}],\"evidence\":[\"a1b2c3d4e5f6\"]}"
      }
    }
  ],
  "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180}
}
```

```json
// tradeloop/tests/fixtures/or_bad_json.json
{
  "id": "gen-bad999",
  "model": "anthropic/claude-sonnet-4.5",
  "object": "chat.completion",
  "choices": [
    {
      "finish_reason": "stop",
      "message": {"role": "assistant", "content": "sorry I cannot help with that"}
    }
  ],
  "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}
}
```

2. Write failing test:

```python
# tradeloop/tests/test_llm_client.py
import json
from pathlib import Path

import httpx
import pytest

from tradeloop.lib.llm import client as client_mod
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.schemas import Shortlist

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def _client(tmp_path, monkeypatch, responses):
    """Build an LLMClient whose httpx.post is a scripted sequence."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-secret")
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        item = responses[min(idx, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json=item, request=httpx.Request("POST", url))

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl", max_retries=3, backoff_base=0.0)
    return c, calls


def test_call_json_validates_and_records_provenance(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_load("or_ok_shortlist.json")])
    out = c.call_json("14_shortlist", "system", "user", Shortlist)
    assert isinstance(out, Shortlist)
    assert out.candidates[0].ticker == "RELIANCE"
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["response_id"] == "gen-abc123"
    assert rec["model_version"] == "anthropic/claude-sonnet-4.5"
    assert rec["prompt_tokens"] == 120 and rec["total_tokens"] == 180
    assert rec["prompt"].endswith("user") and "system" in rec["prompt"]
    assert rec["used_model"] is True


def test_retries_on_transport_error_then_succeeds(tmp_path, monkeypatch):
    err = httpx.ConnectError("boom")
    c, calls = _client(tmp_path, monkeypatch, [err, _load("or_ok_shortlist.json")])
    out = c.call_json("14_shortlist", "s", "u", Shortlist)
    assert isinstance(out, Shortlist)
    assert calls["n"] == 2  # one failure, one success


def test_invalid_json_retried_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_load("or_bad_json.json")])
    with pytest.raises(client_mod.LLMValidationError):
        c.call_json("14_shortlist", "s", "u", Shortlist)
    assert calls["n"] == 3  # exhausted max_retries on invalid output


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl")
    with pytest.raises(client_mod.LLMConfigError):
        c.call_json("14_shortlist", "s", "u", Shortlist)
```

3. Run it (expect FAIL):
```
python -m pytest tradeloop/tests/test_llm_client.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.llm.client'`.

4. Minimal implementation:

```python
# tradeloop/lib/llm/client.py
"""In-process OpenRouter chat-completions client.

Transport reuses the proven pattern in src/tradingbot/llm.py (JSON-only system
prompt, brace-balanced JSON extraction, tolerant content parsing) and adds:
retry/backoff, response_format=json_schema, pydantic validation with retry on
invalid output, and a full provenance CallRecord (model_version / response_id /
prompt / response / token usage) appended to an audit JSONL — the
input-reproducibility half of DoD #3.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError


class LLMConfigError(RuntimeError):
    """Provider disabled or API key missing."""


class LLMValidationError(RuntimeError):
    """Model output could not be parsed/validated against the schema after retries."""


@dataclass(frozen=True)
class CallRecord:
    role: str
    model: str
    model_version: str
    response_id: str
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    used_model: bool
    reason: str = ""


class LLMClient:
    def __init__(
        self,
        audit_path: Path,
        api_key_env: str = "OPENROUTER_API_KEY",
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "anthropic/claude-sonnet-4.5",
        max_tokens: int = 4000,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_seconds = timeout_seconds

    def call_json(
        self, role: str, system: str, user: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        model = model or self.default_model
        api_key = os.getenv(self.api_key_env)  # only sanctioned secret read; never logged
        if not api_key:
            raise LLMConfigError(f"{self.api_key_env} not set")

        prompt = f"{system}\n\n{user}"
        payload = {
            "model": model,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system}\n\n"
                        "You are one bounded agent inside an Indian-market paper trading "
                        "system. India cash equities only, long-only. Return one compact "
                        "JSON object only, matching the given schema. Do not request order "
                        "execution; risk, gate and broker controls are deterministic and final."
                    ),
                },
                {"role": "user", "content": user},
            ],
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
                text = _extract_output_text(body)
                obj = _parse_json_object(text)
                validated = schema.model_validate(obj)
            except (httpx.HTTPError, ValueError, ValidationError) as exc:
                last_exc = exc
                self._record(_failed_record(role, model, prompt, str(exc)))
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base * (2 ** attempt))
                continue
            self._record(CallRecord(
                role=role, model=model,
                model_version=str(body.get("model", model)),
                response_id=str(body.get("id", "")),
                prompt=prompt, response=text,
                prompt_tokens=int(body.get("usage", {}).get("prompt_tokens", 0)),
                completion_tokens=int(body.get("usage", {}).get("completion_tokens", 0)),
                total_tokens=int(body.get("usage", {}).get("total_tokens", 0)),
                used_model=True,
            ))
            return validated

        raise LLMValidationError(f"{role} @ {model} failed after {self.max_retries} tries: {last_exc}")

    def _record(self, record: CallRecord) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record)) + "\n")


def _failed_record(role: str, model: str, prompt: str, reason: str) -> CallRecord:
    return CallRecord(role, model, model, "", prompt, "", 0, 0, 0, False, reason)


def _extract_output_text(body: dict[str, Any]) -> str:
    choices = body.get("choices", [])
    if choices:
        message = choices[0].get("message", {}) or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    raise ValueError("model returned empty content")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    cleaned = _first_json_object(cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("model output must be a JSON object")
    return parsed


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]
```

5. Run pass:
```
python -m pytest tradeloop/tests/test_llm_client.py -q
```
Expected: `4 passed`.

6. Commit:
```
git add tradeloop/lib/llm/client.py tradeloop/tests/test_llm_client.py tradeloop/tests/fixtures/or_ok_shortlist.json tradeloop/tests/fixtures/or_bad_json.json
git commit -m "P1: OpenRouter client with retry/backoff and full provenance audit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `stages.py` — load prompt + inputs, call, validate, write artifact

**Files**
- create `tradeloop/lib/llm/stages.py`
- create `tradeloop/tests/test_llm_stages.py`

**Interfaces**
- Consumes: `client.LLMClient.call_json(role, system, user, schema, model)`; `routing.model_for(stage)`; `schemas.SCHEMA_FOR_STAGE`.
- Produces: `DAG: list[str]` (the 13-role order); `STAGE_INPUTS: dict[str, list[str]]` (named input artifact files per stage, from each prompt's `Reads:` block); `run_stage(name: str, run_dir: Path, client: LLMClient) -> BaseModel` (matches §6 `run_stage(name, run_dir)` plus an injected client for testability); writes `run_dir/<name>.json` (validated) and `run_dir/<name>.md` (human artifact, keeping the existing artifact convention).

`run_stage` loads the markdown prompt at `tradeloop/prompts/<name>.md` (or `shared/…` for adhoc — mapped in `PROMPT_PATH`) as the system prompt, reads each present input artifact from `run_dir` and concatenates them as the user message, calls the model with the stage schema, and writes both the `.json` and a rendered `.md`. Missing optional inputs are skipped (degrade-not-crash, matching the master prompt's intent); a missing prompt file raises. The DAG order matches `00_master_orchestrator.md` steps 1-8.

**Steps**

1. Write failing test:

```python
# tradeloop/tests/test_llm_stages.py
import json
from pathlib import Path

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
```

2. Run it (expect FAIL):
```
python -m pytest tradeloop/tests/test_llm_stages.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.llm.stages'`.

3. Minimal implementation:

```python
# tradeloop/lib/llm/stages.py
"""Run one DAG stage in-process: load prompt + named inputs, call the model,
validate the output against the stage schema (retry once on invalid), and write
both the validated .json and a human-readable .md artifact into the run dir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from tradeloop.lib.llm import routing
from tradeloop.lib.llm.client import LLMValidationError
from tradeloop.lib.llm.schemas import SCHEMA_FOR_STAGE

PROMPTS_DIR = Path("tradeloop") / "prompts"

# 13-role DAG order (00_master_orchestrator.md steps 1-8). 05_adhoc_intake runs
# only in adhoc mode and is invoked separately by the orchestrator.
DAG: list[str] = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical",
    "14_shortlist", "20_bull", "21_bear", "22_debate",
    "30_trade_plan", "40_risk_report", "41_pm_decision",
]

# named input artifacts per stage, from each prompt's Reads: block
STAGE_INPUTS: dict[str, list[str]] = {
    "05_adhoc_intake": ["user_request.md", "00_context.md"],
    "10_news": ["01_news_raw.md", "00_context.md"],
    "11_sentiment": ["10_news.md"],
    "12_fundamentals": ["10_news.md", "00_context.md"],
    "13_technical": ["10_news.md", "02_setups_raw.md", "00_context.md"],
    "14_shortlist": ["10_news.md", "11_sentiment.md", "12_fundamentals.md", "13_technical.md"],
    "20_bull": ["14_shortlist.md"],
    "21_bear": ["14_shortlist.md"],
    "22_debate": ["20_bull.md", "21_bear.md"],
    "30_trade_plan": ["22_debate.md", "13_technical.md", "00_context.md"],
    "40_risk_report": ["30_trade_plan.md", "00_context.md"],
    "41_pm_decision": ["40_risk_report.md", "30_trade_plan.md"],
    "50_post_trade": ["fills.json"],
}

# stages whose prompt file lives under a different name/dir
PROMPT_PATH: dict[str, str] = {
    "10_news": "10_news_analyst",
    "11_sentiment": "11_sentiment_analyst",
    "12_fundamentals": "12_fundamentals_analyst",
    "13_technical": "13_technical_analyst",
    "14_shortlist": "14_shortlister",
    "20_bull": "20_bull_researcher",
    "21_bear": "21_bear_researcher",
    "22_debate": "22_debate_moderator",
    "30_trade_plan": "30_trader",
    "40_risk_report": "40_risk_manager",
    "41_pm_decision": "41_portfolio_manager",
    "50_post_trade": "50_post_trade_analyst",
}


class SupportsCallJson(Protocol):
    def call_json(self, role: str, system: str, user: str,
                  schema: type[BaseModel], model: str | None = None) -> BaseModel: ...


def _prompt_text(name: str) -> str:
    fname = PROMPT_PATH.get(name, name)
    path = PROMPTS_DIR / f"{fname}.md"
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def _user_message(name: str, run_dir: Path) -> str:
    parts: list[str] = []
    for fname in STAGE_INPUTS.get(name, []):
        fpath = run_dir / fname
        if fpath.exists():  # degrade-not-crash on missing optional inputs
            parts.append(f"### {fname}\n{fpath.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) if parts else "(no input artifacts present)"


def run_stage(name: str, run_dir: Path, client: SupportsCallJson) -> BaseModel:
    schema = SCHEMA_FOR_STAGE[name]
    system = _prompt_text(name)
    user = _user_message(name, run_dir)
    model = routing.model_for(name)
    try:
        result = client.call_json(name, system, user, schema, model)
    except LLMValidationError:
        result = client.call_json(name, system, user, schema, model)  # one retry
    (run_dir / f"{name}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / f"{name}.md").write_text(
        f"# {name}\n\n```json\n{result.model_dump_json(indent=2)}\n```\n",
        encoding="utf-8")
    return result
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_llm_stages.py -q
```
Expected: `4 passed`.

5. Commit:
```
git add tradeloop/lib/llm/stages.py tradeloop/tests/test_llm_stages.py
git commit -m "P1: run_stage loads prompt+inputs, validates, writes artifact

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Wire the DAG into the orchestrator's `_run_reasoning()`; serialize `orders.json` from `PMDecision`

**Files**
- modify `tradeloop/orchestrator.py`
- create `tradeloop/tests/test_reasoning_wiring.py`

**Interfaces**
- Consumes: `stages.DAG`, `stages.run_stage`, `client.LLMClient`, `schemas.PMDecision`; the P0 orchestrator's `_run_reasoning(run_dir, mode, agent, timeout)` seam (defined in P0, exec-ing the external CLI, returning an int exit code: `-1` on timeout, `0` on success) and its positional call site in `run_cycle`: `_run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)`.
- Produces: rewritten `_run_reasoning(run_dir, mode, agent, timeout, client=None)` body that runs the DAG in-process and writes `run_dir/orders.json` as `{"mode": mode, "live_orders_enabled": False, "orders": [...], "held": [...]}` serialized **by Python** from the validated `PMDecision` (not the LLM). The P0 order path (`route_orders_file` → `evaluate()`) consumes this unchanged.

Design decision: the new signature keeps `agent, timeout` positionally so P0's `run_cycle` call `_run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)` binds unchanged — no call-site edit is required, and the `agent` param is now unused (the external CLI is gone) but preserved for signature compatibility. `_run_reasoning` builds a default `LLMClient(audit_path=run_dir/"llm_calls.jsonl")` when none is injected (tests inject a fake). It runs `stages.run_stage` for each `name` in `stages.DAG` sequentially, then reads the validated `41_pm_decision.json`, and Python writes `orders.json` in the exact P0 `OrdersFile` object shape. This keeps orders.json authored by code, satisfying the P0 spec's "Python owns routing / orders.json serialization" invariant while P1 owns reasoning. On adhoc mode, `05_adhoc_intake` runs first and its `required_stages` narrows the DAG.

**Cycle-timeout guarantee (preserved from P0):** the in-process DAG must stay bounded by `settings.cycle_timeout_seconds`, exactly as the P0 subprocess `timeout=` did. Concrete mechanism: compute a wall-clock deadline `deadline = time.monotonic() + timeout` before the loop and check it before each `stages.run_stage` call; if the deadline is exceeded, return `-1` so P0's `run_cycle` prints `tradeloop_cycle=TIMEOUT` and exits 1 (the return-code contract is unchanged). `_run_reasoning` returns `0` on normal completion. `run_cycle`'s `rc == -1 → TIMEOUT` branch is therefore preserved with no edit to `run_cycle` itself.

**Steps**

1. Write failing test (uses a fake client keyed by stage; no network):

```python
# tradeloop/tests/test_reasoning_wiring.py
import json
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.llm import schemas


class StageFakeClient:
    """Returns a minimal valid object for whatever stage schema is requested."""
    DEFAULTS = {
        schemas.NewsAnalysis: {"names_in_play": [], "evidence": []},
        schemas.SentimentReport: {"scores": [], "evidence": []},
        schemas.FundamentalsReport: {"tags": [], "evidence": []},
        schemas.TechnicalReport: {"setups": [], "evidence": []},
        schemas.Shortlist: {"candidates": [], "evidence": []},
        schemas.BullCase: {"arguments": [], "evidence": []},
        schemas.BearCase: {"arguments": [], "evidence": []},
        schemas.Debate: {"names": [], "evidence": []},
        schemas.TradePlan: {"tickets": [], "evidence": []},
        schemas.RiskReport: {"decisions": [], "evidence": []},
        schemas.PMDecision: {
            "orders": [{"ticker": "RELIANCE", "side": "BUY", "product": "CNC",
                        "quantity": 8, "price": 2500.0, "order_type": "LIMIT",
                        "reason": "approved"}],
            "held": [], "evidence": ["a1b2c3d4e5f6"],
        },
    }

    def call_json(self, role, system, user, schema, model=None):
        return schema.model_validate(self.DEFAULTS[schema])


def _run_dir(tmp_path):
    d = tmp_path / "runs" / "2026-07-02_0800_premarket"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    return d


def test_reasoning_runs_dag_and_python_writes_orders_json(tmp_path):
    d = _run_dir(tmp_path)
    rc = orchestrator._run_reasoning(d, "premarket", "codex", 1200, client=StageFakeClient())
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert orders["mode"] == "premarket"
    assert orders["live_orders_enabled"] is False
    assert orders["orders"][0]["ticker"] == "RELIANCE"
    assert orders["orders"][0]["side"] == "BUY"
    # PM stage artifact was validated and written
    assert (d / "41_pm_decision.json").exists()
```

2. Run it (expect FAIL — old `_run_reasoning` exec's the CLI / signature lacks `client`):
```
python -m pytest tradeloop/tests/test_reasoning_wiring.py -q
```
Expected: FAIL (either `TypeError: _run_reasoning() got an unexpected keyword argument 'client'` or the CLI-exec body produces no `41_pm_decision.json`).

3. Minimal implementation — replace the `_run_reasoning` body in `tradeloop/orchestrator.py`:

```python
# tradeloop/orchestrator.py  (replace the P0 _run_reasoning body)
import json
import time

from tradeloop.lib.llm import stages
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.schemas import PMDecision


def _run_reasoning(run_dir, mode, agent, timeout, client=None):
    """P1: run the 13-role DAG in-process (was: exec external codex/claude CLI).

    Signature preserves P0's positional (run_dir, mode, agent, timeout): run_cycle
    still calls _run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)
    unchanged. `agent` is now unused (no external CLI) but kept for compat.

    Each stage returns a validated pydantic form written to run_dir/<stage>.json.
    Python — not the LLM — then serialises orders.json from the validated
    PMDecision, preserving the P0 order-path contract (route_orders_file reads
    the OrdersFile object shape and runs evaluate() on every order).

    Returns an int exit code matching P0's contract: -1 on cycle-timeout
    (run_cycle → TIMEOUT, exit 1), 0 on success.
    """
    client = client or LLMClient(audit_path=run_dir / "llm_calls.jsonl")
    deadline = time.monotonic() + timeout  # bound the DAG exactly as P0's subprocess timeout= did

    dag = list(stages.DAG)
    if mode == "adhoc" and (run_dir / "user_request.md").exists():
        if time.monotonic() > deadline:
            return -1
        intake = stages.run_stage("05_adhoc_intake", run_dir, client)
        wanted = {s.removesuffix(".md") for s in intake.required_stages}
        if wanted:
            dag = [s for s in dag if s in wanted]

    for name in dag:
        if time.monotonic() > deadline:
            return -1
        stages.run_stage(name, run_dir, client)

    pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,      # paper default; live only past promotion gate
        "generated_by": "tradeloop.reasoning.p1",
        "orders": [o.model_dump() for o in pm.orders],
        "held": [o.model_dump() for o in pm.held],
    }
    (run_dir / "orders.json").write_text(json.dumps(orders_file, indent=2), encoding="utf-8")
    return 0
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_reasoning_wiring.py -q
```
Expected: `1 passed`.

5. Commit:
```
git add tradeloop/orchestrator.py tradeloop/tests/test_reasoning_wiring.py
git commit -m "P1: run reasoning DAG in-process; Python serialises orders.json from PMDecision

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Replace fake model IDs in `model_routing.md`; full-suite green

**Files**
- modify `tradeloop/prompts/shared/model_routing.md`
- create `tradeloop/tests/test_model_routing_doc.py`

**Interfaces**
- Consumes: `routing.STAGE_MODELS`.
- Produces: doc whose OpenRouter table matches `routing.STAGE_MODELS` and contains no placeholder IDs.

**Steps**

1. Write failing test:

```python
# tradeloop/tests/test_model_routing_doc.py
from pathlib import Path

from tradeloop.lib.llm import routing

DOC = Path("tradeloop/prompts/shared/model_routing.md")


def test_doc_has_no_fake_model_ids():
    text = DOC.read_text()
    for fake in ("minimax/minimax-m3", "deepseek/deepseek-v4-flash",
                 "xiaomi/mimo-v2.5", "tencent/hy3-preview"):
        assert fake not in text, f"placeholder model {fake} still in doc"


def test_doc_lists_every_real_stage_model():
    text = DOC.read_text()
    for model in set(routing.STAGE_MODELS.values()):
        assert model in text, f"{model} missing from routing doc"
```

2. Run it (expect FAIL — the doc still contains the four placeholders):
```
python -m pytest tradeloop/tests/test_model_routing_doc.py -q
```
Expected: FAIL on `test_doc_has_no_fake_model_ids`.

3. Minimal implementation — rewrite the OpenRouter section of `tradeloop/prompts/shared/model_routing.md` so the table reads (replacing lines 15-36):

```markdown
## OpenRouter model assignments (Python reasoning layer)

Python calls OpenRouter directly per stage (see `tradeloop/lib/llm/routing.py`,
the single source of truth). Tier intent: haiku=classify, sonnet=analysis,
opus=high-stakes decisions.

| Stage | Team | Model |
| --- | --- | --- |
| `05_adhoc_intake` | Ad Hoc Intake | `anthropic/claude-haiku-4.5` |
| `10_news` | News Analyst | `deepseek/deepseek-v3.2` |
| `11_sentiment` | Sentiment Analyst | `anthropic/claude-haiku-4.5` |
| `12_fundamentals` | Fundamentals Analyst | `anthropic/claude-sonnet-4.5` |
| `13_technical` | Technical Analyst | `deepseek/deepseek-v3.2` |
| `14_shortlist` | Shortlister | `anthropic/claude-sonnet-4.5` |
| `20_bull` | Bull Researcher | `anthropic/claude-sonnet-4.5` |
| `21_bear` | Bear Researcher | `anthropic/claude-sonnet-4.5` |
| `22_debate` | Debate Moderator | `anthropic/claude-opus-4.5` |
| `30_trade_plan` | Trader | `anthropic/claude-opus-4.5` |
| `40_risk_report` | Risk Manager | `anthropic/claude-opus-4.5` |
| `41_pm_decision` | Portfolio Manager | `anthropic/claude-opus-4.5` |
| `50_post_trade` | Post Trade Analyst | `anthropic/claude-sonnet-4.5` |

Routing rules: exact slugs are pinned above; `~anthropic/claude-*-latest`
tilde-aliases resolve to the newest in-family version if a pinned slug is
retired. Structured output uses `response_format: {type: json_schema}`;
brace-balanced JSON extraction is the universal fallback for providers that do
not honor it.
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_model_routing_doc.py -q
```
Expected: `2 passed`.

5. Run the whole Phase-1 suite:
```
python -m pytest tradeloop/tests/test_llm_routing.py tradeloop/tests/test_llm_schemas.py tradeloop/tests/test_llm_client.py tradeloop/tests/test_llm_stages.py tradeloop/tests/test_reasoning_wiring.py tradeloop/tests/test_model_routing_doc.py -q
```
Expected: all pass (20 tests).

6. Commit:
```
git add tradeloop/prompts/shared/model_routing.md tradeloop/tests/test_model_routing_doc.py
git commit -m "P1: replace fake OpenRouter model IDs in routing doc with real slugs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review

**Spec/DoD coverage (Phase 1 = DoD #3 first half — input-reproducibility):**
- *Python calls the model directly (no external CLI):* Task 5 replaces `_run_reasoning`'s exec body with in-process `stages.run_stage` over `stages.DAG`.
- *Reuses the proven `src/tradingbot/llm.py` pattern:* Task 3 carries over `_extract_output_text`, `_parse_json_object`, `_first_json_object` (brace-balanced dedupe) and the JSON-only system prompt verbatim, adding retry/backoff.
- *Records model_version/response_id/prompt/response/token-usage per call:* Task 3 `CallRecord` captures `body["model"]`, `body["id"]`, prompt, response text, and `usage.{prompt,completion,total}_tokens`, appended to `llm_calls.jsonl` — the input-reproducibility half of DoD #3, tested in `test_llm_client.py`.
- *`routing.py` with real IDs:* Task 1 replaces the fake `minimax/mimo/hy3/deepseek-v4-flash` IDs with confirmed-current `anthropic/claude-{haiku,sonnet,opus}-4.5` + `deepseek/deepseek-v3.2`; Task 6 syncs the doc and guards against regression.
- *`schemas.py` per-stage pydantic with evidence trailer:* Task 2 — shortlist candidate, unified Trade Ticket (reconciling `30_trader.md` + `output_schemas.md`), debate `{conviction,verdict}`, risk decision, PM/orders; `EvidenceMixin.evidence: list[str]` on every recommendation-bearing model (validated against snapshot in P3).
- *`stages.run_stage(name, run_dir)` loads prompt + inputs, validates, retries on invalid, writes artifact:* Task 4 (client injected for testability; the §6 two-arg call is the default-client path in Task 5).
- *13-role DAG + tiers preserved:* `stages.DAG` + `routing.STAGE_MODELS` keep the `00_master_orchestrator.md` order and haiku/sonnet/opus intent.
- *Constraints preserved:* order path (`evaluate()`), paper default, kill-switch, long-only are all in the untouched P0 order path; the PM schema is long-only-shaped and Python (not the LLM) writes `orders.json` with `live_orders_enabled=False`.

**Placeholder scan:** No "TBD"/"similar to Task N"/"add error handling" text. Every task shows complete real test code and complete real implementation. Every referenced type is defined: `Order`, `EvidenceMixin`, all 13 stage models, `SCHEMA_FOR_STAGE` (Task 2); `CallRecord`, `LLMClient`, `LLMConfigError`, `LLMValidationError`, `_extract_output_text`, `_parse_json_object`, `_first_json_object` (Task 3); `DAG`, `STAGE_INPUTS`, `PROMPT_PATH`, `run_stage` (Task 4); `_run_reasoning` (Task 5). The two recorded fixtures are written out in full (Task 3).

**Type-consistency:** `call_json(role, system, user, schema, model=None) -> BaseModel` matches §6 (extra optional `model` for stage routing; the §6 four-arg form is the default-model path). `run_stage(name, run_dir, client)` matches §6 `run_stage(name, run_dir)` with an injected client (default-constructed in Task 5's `_run_reasoning`, so the production call site is two-arg-equivalent). `PMDecision.orders: list[Order]` uses the exact P0 `orders_schema.Order` field shape (`side` Literal["BUY","SELL"], `product` Literal["CNC","MIS"], `quantity>0`, `price>0`, `hard_stop/target_1/target_2/strategy_family/reason`), so the Python-serialized `orders.json` parses cleanly through P0's `load_orders` → `to_ticket` → `evaluate`. No test performs live network I/O — `httpx.post` is monkeypatched and stage clients are fakes.
