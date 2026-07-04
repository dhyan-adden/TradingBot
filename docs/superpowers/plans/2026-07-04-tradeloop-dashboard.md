# TradeLoop Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, dependency-free web dashboard that renders each morning TradeLoop run's stages as plain-English cards - live as they complete and for past runs - for a non-technical user.

**Architecture:** Three small units: a pure `render` module that turns a raw stage dict into a friendly `StageView` (plus a jargon `GLOSSARY`); a `runs` module that lists run folders and reads a run's stage files; a stdlib `http.server` that serves one HTML page and JSON endpoints the page polls. The page is read-only except one button that launches a propose cycle on the Claude backend.

**Tech Stack:** Python 3.11 standard library only (`http.server`, `json`, `pathlib`, `dataclasses`, `subprocess`, `webbrowser`). No new dependencies. Runs in the existing conda env (`/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python`). One HTML page with inline CSS/JS, no frontend framework.

## Global Constraints

- Standard library only - no new dependencies.
- Read-only over run data: the dashboard never edits a run, never approves or places a trade. The single writing route is `POST /api/run-now`, which only launches a **propose** cycle (`run_cycle`, backend `claude`), never `route_cycle`.
- No per-view AI cost: all translation is deterministic templates + the static `GLOSSARY`.
- Stage output shapes are defined in `tradeloop/lib/llm/schemas.py` (authoritative); render reads the per-stage `.json` files defensively (missing keys tolerated).
- Test interpreter: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest`.
- Run under `-W error` like the rest of the suite where practical.

---

### Task 1: Render core + analysis-stage cards (`render.py`)

**Files:**
- Create: `tradeloop/dashboard/__init__.py` (empty)
- Create: `tradeloop/dashboard/render.py`
- Create: `tradeloop/tests/dashboard/__init__.py` (empty)
- Test: `tradeloop/tests/dashboard/test_render.py`

**Interfaces:**
- Produces:
  - `@dataclass StageView(stage: str, icon: str, title: str, role: str, summary: str, points: list[str], status: str = "done")`
  - `STAGE_META: dict[str, tuple[str, str, str]]` - `stage -> (icon, title, role)` for all 13 stages.
  - `GLOSSARY: dict[str, str]` - lower-cased term -> plain explanation.
  - `COMPANY_NAMES: dict[str, str]`; `pretty_ticker(t: str) -> str`.
  - `render_stage(stage: str, raw: dict) -> StageView` - dispatches to a per-stage builder; unknown stage -> generic card.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/dashboard/test_render.py
from tradeloop.dashboard.render import (
    STAGE_META, GLOSSARY, pretty_ticker, render_stage, StageView,
)


def test_pretty_ticker_maps_known_and_falls_back():
    assert pretty_ticker("HDFCBANK") == "HDFC Bank"
    assert pretty_ticker("UNKNOWNXY") == "UNKNOWNXY"


def test_every_stage_has_meta():
    for stage in ("10_news", "11_sentiment", "12_fundamentals", "13_technical",
                  "14_shortlist", "20_bull", "21_bear", "22_debate",
                  "30_trade_plan", "40_risk_report", "41_pm_decision"):
        icon, title, role = STAGE_META[stage]
        assert icon and title and role


def test_news_card_lists_names_in_plain_english():
    raw = {"macro_context": "Banks firm on rate hopes",
           "names_in_play": [{"ticker": "HDFCBANK", "catalyst": "strong Q1 update", "tier": "A"}],
           "macro_themes": ["rate cut hopes"]}
    view = render_stage("10_news", raw)
    assert isinstance(view, StageView)
    assert view.title == "News Expert" and view.icon
    assert "HDFC Bank" in view.summary or any("HDFC Bank" in p for p in view.points)
    assert any("strong Q1 update" in p for p in view.points)


def test_technical_card_translates_classification():
    raw = {"setups": [{"ticker": "SBIN", "classification": "bullish_entry",
                       "news_confirmed": True, "notes": "pullback to EMA20"}]}
    view = render_stage("13_technical", raw)
    assert any("SBIN" in p or "State Bank" in p for p in view.points)
    assert "bullish_entry" not in view.summary  # translated, not raw enum


def test_shortlist_card_ranks_candidates():
    raw = {"candidates": [
        {"ticker": "HDFCBANK", "composite_score": 7.5, "thesis": "breakout on Q1", "catalyst_type": "earnings", "source_track": "tier_a", "horizon": "1-5 days"},
        {"ticker": "SBIN", "composite_score": 4.0, "thesis": "weak pullback", "catalyst_type": "technical", "source_track": "tier_b", "horizon": "1-5 days"}]}
    view = render_stage("14_shortlist", raw)
    assert "2" in view.summary  # count of candidates
    assert view.points[0].startswith("HDFC Bank")  # highest score first


def test_glossary_has_core_terms():
    for term in ("cnc", "hard stop", "breakout", "conviction", "swing"):
        assert term in GLOSSARY and GLOSSARY[term]


def test_unknown_stage_returns_generic_card():
    view = render_stage("99_unknown", {"foo": "bar"})
    assert view.status == "done" and view.title
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_render.py -q`
Expected: FAIL - `ModuleNotFoundError: No module named 'tradeloop.dashboard'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradeloop/dashboard/render.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StageView:
    stage: str
    icon: str
    title: str
    role: str
    summary: str
    points: list[str] = field(default_factory=list)
    status: str = "done"


# stage -> (icon, friendly name, one-line "what this expert does")
STAGE_META: dict[str, tuple[str, str, str]] = {
    "10_news": ("news", "News Expert", "Reads the morning's headlines and finds stocks with a story behind them."),
    "11_sentiment": ("chat", "Mood Expert", "Gauges how retail traders and social media feel about each stock."),
    "12_fundamentals": ("book", "Health Expert", "Checks each company's financial health for red flags."),
    "13_technical": ("chart", "Chart Expert", "Reads the price charts to spot clean, tradeable setups."),
    "14_shortlist": ("list", "Shortlister", "Combines every expert's view into today's ranked list of candidates."),
    "20_bull": ("bull", "The Optimist", "Argues the strongest case FOR buying each candidate."),
    "21_bear": ("bear", "The Skeptic", "Argues the strongest case AGAINST each candidate."),
    "22_debate": ("scale", "The Judge", "Weighs optimist vs skeptic and rates each stock's conviction."),
    "30_trade_plan": ("target", "The Trader", "Turns a green-lit idea into an exact plan: buy price, stop, targets, size."),
    "40_risk_report": ("shield", "Risk Manager", "Checks every plan against the risk limits and resizes or rejects it."),
    "41_pm_decision": ("gavel", "Final Decision", "The portfolio manager's final call on what to propose today."),
    "05_adhoc_intake": ("inbox", "Request Intake", "Interprets a one-off research or trade request."),
    "50_post_trade": ("clipboard", "Post-Trade Review", "After trades close, records what happened and the lesson."),
}

COMPANY_NAMES: dict[str, str] = {
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "SBIN": "State Bank of India",
    "RELIANCE": "Reliance Industries",
    "INFY": "Infosys",
    "TCS": "TCS",
    "WIPRO": "Wipro",
    "HCLTECH": "HCL Technologies",
    "DLF": "DLF",
}


def pretty_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    return COMPANY_NAMES.get(t, t)


GLOSSARY: dict[str, str] = {
    "cnc": "A regular delivery buy - you own the shares (no borrowing, no leverage).",
    "mis": "An intraday product - bought and sold the same day.",
    "hard stop": "The price where the trade is cut to limit the loss.",
    "breakout": "When a price pushes above a level it had been stuck under - often a sign of momentum.",
    "pullback": "A small dip in an uptrend - sometimes a lower-risk spot to buy.",
    "conviction": "How confident the bot is, on a 0-10 scale.",
    "swing": "A trade held for a few days to a few weeks (not same-day).",
    "atr": "A measure of how much a stock typically moves in a day - used to set a sensible stop.",
    "catalyst": "A specific reason (like news or earnings) that could move the stock.",
    "tier a": "Top-quality source or signal; tier B and C are progressively weaker.",
    "echo chamber": "When online buzz is just people repeating each other, not real signal.",
    "long-only": "The bot only buys (and later sells to exit) - it never bets on prices falling.",
    "target": "A price where the bot plans to take profit.",
}

_CLASSIFY = {
    "bullish_entry": "a fresh buy signal",
    "bullish_continuation": "an ongoing uptrend worth staying with",
    "exit_watch": "a name to watch for an exit, not a buy",
    "avoid": "best avoided right now",
}
_VERDICT = {"tradeable": "green-lit to trade", "watch": "worth watching, not yet", "pass": "passed on"}
_TAG = {"green": "healthy", "yellow": "some caution", "red": "red flags"}


def _meta(stage: str) -> tuple[str, str, str]:
    return STAGE_META.get(stage, ("dot", stage, ""))


def _news(raw: dict) -> tuple[str, list[str]]:
    names = raw.get("names_in_play") or []
    macro = (raw.get("macro_context") or "").strip()
    summary = macro or "Scanned the morning's headlines."
    points = [f"{pretty_ticker(n.get('ticker',''))}: {n.get('catalyst','')} (tier {n.get('tier','?')})"
              for n in names]
    if not points:
        points = ["No fresh stock-specific news stood out today."]
    return summary, points


def _sentiment(raw: dict) -> tuple[str, list[str]]:
    scores = raw.get("scores") or []
    points = []
    for s in scores:
        val = s.get("sentiment_score", 0)
        mood = "positive" if val > 0.15 else "negative" if val < -0.15 else "neutral"
        echo = " (looks like echo-chamber buzz)" if s.get("echo_chamber_flag") else ""
        points.append(f"{pretty_ticker(s.get('ticker',''))}: {mood} mood{echo}")
    return ("How the crowd feels about each name." if points else "No notable social buzz."), points


def _fundamentals(raw: dict) -> tuple[str, list[str]]:
    tags = raw.get("tags") or []
    points = []
    for t in tags:
        flags = ", ".join(t.get("red_flags") or [])
        extra = f" - {flags}" if flags else ""
        points.append(f"{pretty_ticker(t.get('ticker',''))}: {_TAG.get(t.get('tag'), t.get('tag',''))}{extra}")
    return ("Financial-health check on each candidate." if points else "No fundamentals flagged."), points


def _technical(raw: dict) -> tuple[str, list[str]]:
    setups = raw.get("setups") or []
    points = []
    for s in setups:
        cls = _CLASSIFY.get(s.get("classification"), s.get("classification", ""))
        confirmed = " (news backs it up)" if s.get("news_confirmed") else ""
        note = f" - {s.get('notes')}" if s.get("notes") else ""
        points.append(f"{pretty_ticker(s.get('ticker',''))}: {cls}{confirmed}{note}")
    return ("What the price charts say." if points else "No clean chart setups today."), points


def _shortlist(raw: dict) -> tuple[str, list[str]]:
    cands = sorted(raw.get("candidates") or [], key=lambda c: c.get("composite_score", 0), reverse=True)
    summary = f"Today's ranked shortlist: {len(cands)} candidate(s)."
    points = [f"{pretty_ticker(c.get('ticker',''))} (score {c.get('composite_score','?')}/10): {c.get('thesis','')}"
              for c in cands]
    if not points:
        points = ["Nothing made the shortlist today."]
    return summary, points


def _args(raw: dict, lead: str) -> tuple[str, list[str]]:
    args = raw.get("arguments") or []
    points = [f"{pretty_ticker(a.get('ticker',''))}: {a.get('claim','')}" for a in args]
    return (lead if points else lead + " (nothing to argue today)"), points


def _debate(raw: dict) -> tuple[str, list[str]]:
    names = raw.get("names") or []
    points = [f"{pretty_ticker(n.get('ticker',''))}: {_VERDICT.get(n.get('verdict'), n.get('verdict',''))} "
              f"(conviction {n.get('conviction','?')}/10)" for n in names]
    tradeable = [n for n in names if n.get("verdict") == "tradeable"]
    summary = (f"{len(tradeable)} name(s) green-lit to trade." if tradeable
               else "Cautious today - nothing green-lit to trade.")
    return summary, (points or ["No names debated."])


_ANALYSIS_BUILDERS = {
    "10_news": _news, "11_sentiment": _sentiment, "12_fundamentals": _fundamentals,
    "13_technical": _technical, "14_shortlist": _shortlist,
    "20_bull": lambda r: _args(r, "The case FOR buying:"),
    "21_bear": lambda r: _args(r, "The case AGAINST:"),
    "22_debate": _debate,
}


def render_stage(stage: str, raw: dict) -> StageView:
    icon, title, role = _meta(stage)
    raw = raw or {}
    builder = _ANALYSIS_BUILDERS.get(stage)
    if builder is not None:
        summary, points = builder(raw)
    else:
        # Task 2 fills 30/40/41; until then, and for any unknown stage, a generic card.
        summary, points = "", []
    return StageView(stage=stage, icon=icon, title=title, role=role, summary=summary, points=points)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_render.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/dashboard/__init__.py tradeloop/dashboard/render.py tradeloop/tests/dashboard/
git commit -m "dashboard: render core + analysis-stage cards"
```

---

### Task 2: Decision-stage cards (trader, risk, final decision)

**Files:**
- Modify: `tradeloop/dashboard/render.py` (add builders + wire into dispatch)
- Test: `tradeloop/tests/dashboard/test_render_decisions.py`

**Interfaces:**
- Consumes: `StageView`, `pretty_ticker`, `render_stage` from Task 1.
- Produces: `render_decision(orders_json: dict) -> StageView` - a plain-English final-decision card built from `orders.json` (fields `orders`, `held`).

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/dashboard/test_render_decisions.py
from tradeloop.dashboard.render import render_stage, render_decision


def test_trade_plan_card_states_the_trade():
    raw = {"tickets": [{"ticker": "HDFCBANK", "side": "BUY", "quantity": 25,
                        "entry": 801.05, "hard_stop": 779.48, "target_1": 829.8,
                        "target_2": 844.2, "thesis": "Q1 breakout", "conviction": 7.0}]}
    view = render_stage("30_trade_plan", raw)
    p = " ".join(view.points)
    assert "HDFC Bank" in p and "25" in p and "801.05" in p and "779.48" in p


def test_risk_card_translates_decision():
    raw = {"decisions": [{"ticker": "HDFCBANK", "decision": "resize",
                         "resized_quantity": 14, "reasons": ["position cap"]}]}
    view = render_stage("40_risk_report", raw)
    p = " ".join(view.points)
    assert "HDFC Bank" in p and "14" in p and "resize" not in view.summary.lower()


def test_decision_card_buy():
    orders = {"orders": [{"ticker": "HDFCBANK", "side": "BUY", "quantity": 25,
                          "price": 801.05, "hard_stop": 779.48, "reason": "breakout"}], "held": []}
    view = render_decision(orders)
    assert "Proposing to BUY" in view.summary and "HDFC Bank" in view.summary


def test_decision_card_hold():
    view = render_decision({"orders": [], "held": []})
    assert "Holding" in view.summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_render_decisions.py -q`
Expected: FAIL - `ImportError: cannot import name 'render_decision'`

- [ ] **Step 3: Write minimal implementation**

Add to `tradeloop/dashboard/render.py`:

```python
_RISK = {"approve": "approved as-is", "resize": "approved but resized", "reject": "rejected"}


def _trade_plan(raw: dict) -> tuple[str, list[str]]:
    tickets = raw.get("tickets") or []
    points = []
    for t in tickets:
        points.append(
            f"{t.get('side','BUY')} {t.get('quantity','?')} shares of {pretty_ticker(t.get('ticker',''))} "
            f"at {t.get('entry','?')}, stop {t.get('hard_stop','?')}, "
            f"targets {t.get('target_1','?')} / {t.get('target_2','?')}. Why: {t.get('thesis','')}")
    return (f"{len(tickets)} trade plan(s) drawn up." if tickets else "No trade plans - nothing qualified."), points


def _risk(raw: dict) -> tuple[str, list[str]]:
    rows = raw.get("decisions") or []
    points = []
    for r in rows:
        q = r.get("resized_quantity")
        qty = f" to {q} shares" if r.get("decision") == "resize" and q is not None else ""
        why = ("; ".join(r.get("reasons") or []))
        points.append(f"{pretty_ticker(r.get('ticker',''))}: {_RISK.get(r.get('decision'), r.get('decision',''))}{qty}"
                      + (f" - {why}" if why else ""))
    return ("Risk check on each plan." if points else "No plans reached the risk check."), points


def render_decision(orders_json: dict) -> StageView:
    icon, title, role = _meta("41_pm_decision")
    orders = (orders_json or {}).get("orders") or []
    if not orders:
        summary = "Holding today - nothing convincing enough to propose."
        points = []
    else:
        first = orders[0]
        summary = (f"Proposing to {first.get('side','BUY')} {first.get('quantity','?')} shares of "
                   f"{pretty_ticker(first.get('ticker',''))} at {first.get('price','?')}.")
        points = [f"{o.get('side','BUY')} {o.get('quantity','?')} {pretty_ticker(o.get('ticker',''))} "
                  f"@ {o.get('price','?')} - {o.get('reason','')}" for o in orders]
    return StageView(stage="41_pm_decision", icon=icon, title=title, role=role, summary=summary, points=points)
```

Wire the new builders into dispatch - replace the `_ANALYSIS_BUILDERS` additions by extending the dict:

```python
_ANALYSIS_BUILDERS["30_trade_plan"] = _trade_plan
_ANALYSIS_BUILDERS["40_risk_report"] = _risk
```

(Place these two lines after `render_decision` is defined, at module level.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/ -q`
Expected: PASS (all render tests)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/dashboard/render.py tradeloop/tests/dashboard/test_render_decisions.py
git commit -m "dashboard: trader, risk, and final-decision cards"
```

---

### Task 3: Read run folders (`runs.py`)

**Files:**
- Create: `tradeloop/dashboard/runs.py`
- Test: `tradeloop/tests/dashboard/test_runs.py`

**Interfaces:**
- Consumes: `render_stage`, `render_decision`, `StageView` from Tasks 1-2.
- Produces:
  - `STAGE_ORDER: list[str]` - the display order of stage names.
  - `@dataclass RunSummary(dir_name: str, mode: str, decision: str)`
  - `list_runs(runs_dir: Path) -> list[RunSummary]` - newest first.
  - `read_run(run_dir: Path) -> dict` - `{"dir": name, "live": bool, "stages": [StageView-as-dict...], "decision": StageView-as-dict}`. A run is `live` when `41_pm_decision.json` is absent.

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/dashboard/test_runs.py
import json
from pathlib import Path

from tradeloop.dashboard.runs import list_runs, read_run


def _make_run(runs_dir: Path, name: str, with_decision: bool):
    d = runs_dir / name
    d.mkdir(parents=True)
    (d / "10_news.json").write_text(json.dumps(
        {"names_in_play": [{"ticker": "HDFCBANK", "catalyst": "Q1", "tier": "A"}]}))
    if with_decision:
        (d / "41_pm_decision.json").write_text(json.dumps({"orders": [], "held": []}))
        (d / "orders.json").write_text(json.dumps({"orders": [], "held": []}))
    return d


def test_list_runs_newest_first(tmp_path):
    _make_run(tmp_path, "2026-07-03_0900_premarket", True)
    _make_run(tmp_path, "2026-07-04_0900_premarket", True)
    runs = list_runs(tmp_path)
    assert [r.dir_name for r in runs][0] == "2026-07-04_0900_premarket"
    assert runs[0].mode == "premarket"


def test_read_run_complete_has_stages_and_decision(tmp_path):
    d = _make_run(tmp_path, "2026-07-04_0900_premarket", True)
    out = read_run(d)
    assert out["live"] is False
    stages = {s["stage"] for s in out["stages"]}
    assert "10_news" in stages
    assert out["decision"]["summary"]


def test_read_run_live_when_no_decision(tmp_path):
    d = _make_run(tmp_path, "2026-07-04_0900_premarket", False)
    out = read_run(d)
    assert out["live"] is True


def test_read_run_tolerates_missing_and_malformed_files(tmp_path):
    d = tmp_path / "2026-07-04_0900_premarket"
    d.mkdir()
    (d / "10_news.json").write_text("{ this is not json")
    out = read_run(d)  # must not raise
    assert isinstance(out["stages"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_runs.py -q`
Expected: FAIL - `ModuleNotFoundError: No module named 'tradeloop.dashboard.runs'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradeloop/dashboard/runs.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tradeloop.dashboard.render import render_decision, render_stage

STAGE_ORDER = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical", "14_shortlist",
    "20_bull", "21_bear", "22_debate", "30_trade_plan", "40_risk_report",
]


@dataclass
class RunSummary:
    dir_name: str
    mode: str
    decision: str


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}  # malformed -> empty, never crash


def _mode(dir_name: str) -> str:
    return dir_name.rsplit("_", 1)[-1] if "_" in dir_name else ""


def list_runs(runs_dir: Path) -> list[RunSummary]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    out = []
    for d in sorted((p for p in runs_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        orders = _load(d / "orders.json") or {}
        dec = render_decision(orders)
        out.append(RunSummary(dir_name=d.name, mode=_mode(d.name), decision=dec.summary))
    return out


def read_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    stages = []
    for stage in STAGE_ORDER:
        raw = _load(run_dir / f"{stage}.json")
        if raw is None:
            continue  # not written yet
        stages.append(asdict(render_stage(stage, raw)))
    decision_raw = _load(run_dir / "41_pm_decision.json")
    live = decision_raw is None
    orders = _load(run_dir / "orders.json") or {}
    decision = asdict(render_decision(orders))
    return {"dir": run_dir.name, "live": live, "stages": stages, "decision": decision}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_runs.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/dashboard/runs.py tradeloop/tests/dashboard/test_runs.py
git commit -m "dashboard: read run folders into friendly stage views"
```

---

### Task 4: Read-only HTTP server (`server.py`)

**Files:**
- Create: `tradeloop/dashboard/server.py`
- Test: `tradeloop/tests/dashboard/test_server.py`

**Interfaces:**
- Consumes: `list_runs`, `read_run` (Task 3).
- Produces:
  - `handle_api(path: str, query: dict, runs_dir: Path) -> tuple[int, dict]` - pure routing for the read APIs (`/api/runs`, `/api/run`), returns `(status_code, json_body)`. Kept separate from the socket layer so it is unit-testable without a live server.
  - `make_handler(runs_dir: Path, static_dir: Path)` -> a `BaseHTTPRequestHandler` subclass serving `GET /`, `GET /api/runs`, `GET /api/run?dir=...`. (POST `/api/run-now` is added in Task 6.)

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/dashboard/test_server.py
import json
from pathlib import Path

from tradeloop.dashboard.server import handle_api


def _seed(tmp_path):
    d = tmp_path / "2026-07-04_0900_premarket"
    d.mkdir(parents=True)
    (d / "10_news.json").write_text(json.dumps({"names_in_play": []}))
    (d / "orders.json").write_text(json.dumps({"orders": [], "held": []}))
    return tmp_path


def test_api_runs_lists(tmp_path):
    runs_dir = _seed(tmp_path)
    status, body = handle_api("/api/runs", {}, runs_dir)
    assert status == 200
    assert body["runs"][0]["dir_name"] == "2026-07-04_0900_premarket"


def test_api_run_reads_one(tmp_path):
    runs_dir = _seed(tmp_path)
    status, body = handle_api("/api/run", {"dir": ["2026-07-04_0900_premarket"]}, runs_dir)
    assert status == 200
    assert body["dir"] == "2026-07-04_0900_premarket"
    assert "stages" in body


def test_api_run_rejects_path_traversal(tmp_path):
    runs_dir = _seed(tmp_path)
    status, _ = handle_api("/api/run", {"dir": ["../../etc"]}, runs_dir)
    assert status == 400


def test_api_unknown_route_404(tmp_path):
    status, _ = handle_api("/api/nope", {}, tmp_path)
    assert status == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_server.py -q`
Expected: FAIL - `ModuleNotFoundError: No module named 'tradeloop.dashboard.server'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradeloop/dashboard/server.py
from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tradeloop.dashboard.runs import list_runs, read_run


def _safe_run_dir(runs_dir: Path, name: str) -> Path | None:
    # only a direct child of runs_dir, no traversal
    candidate = (runs_dir / name).resolve()
    if candidate.parent != runs_dir.resolve() or not candidate.is_dir():
        return None
    return candidate


def handle_api(path: str, query: dict, runs_dir: Path) -> tuple[int, dict]:
    runs_dir = Path(runs_dir)
    if path == "/api/runs":
        return 200, {"runs": [asdict(r) for r in list_runs(runs_dir)]}
    if path == "/api/run":
        name = (query.get("dir") or [""])[0]
        d = _safe_run_dir(runs_dir, name)
        if d is None:
            return 400, {"error": "bad run dir"}
        return 200, read_run(d)
    return 404, {"error": "not found"}


def make_handler(runs_dir: Path, static_dir: Path):
    runs_dir = Path(runs_dir)
    static_dir = Path(static_dir)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body_bytes, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                html = (static_dir / "index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if parsed.path.startswith("/api/"):
                status, body = handle_api(parsed.path, parse_qs(parsed.query), runs_dir)
                return self._json(status, body)
            self._json(404, {"error": "not found"})

        def log_message(self, *args):  # quiet
            pass

    return Handler
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_server.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/dashboard/server.py tradeloop/tests/dashboard/test_server.py
git commit -m "dashboard: read-only JSON API + static page server"
```

---

### Task 5: The page + entry point (`index.html`, `__main__.py`)

**Files:**
- Create: `tradeloop/dashboard/static/index.html`
- Create: `tradeloop/dashboard/__main__.py`

**Interfaces:**
- Consumes: `make_handler` (Task 4). The page calls `GET /api/runs` and `GET /api/run?dir=...`; while a run is `live` it re-polls every 1.5s.

- [ ] **Step 1: Write the page**

```html
<!-- tradeloop/dashboard/static/index.html -->
<!doctype html>
<meta charset="utf-8">
<title>TradeLoop</title>
<style>
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 780px; margin: 24px auto; padding: 0 16px; color: #1a1a1a; }
  h1 { font-size: 22px; }
  select, button { font: inherit; padding: 6px 10px; }
  .card { border: 1px solid #e2e2e2; border-radius: 10px; padding: 14px 16px; margin: 12px 0; }
  .card h3 { margin: 0 0 2px; font-size: 17px; }
  .role { color: #666; font-size: 13px; margin: 0 0 8px; }
  .summary { font-weight: 600; margin: 0 0 6px; }
  ul { margin: 6px 0 0; padding-left: 20px; }
  .decision { border-color: #2b7; background: #f3fbf6; }
  .waiting { color: #999; font-style: italic; }
  #bar { display: flex; gap: 10px; align-items: center; }
</style>
<h1>TradeLoop - what the bot is thinking</h1>
<div id="bar">
  <button id="runNow">Run now</button>
  <select id="picker"></select>
  <span id="status"></span>
</div>
<div id="cards"></div>
<script>
let current = null, timer = null;

async function loadRuns() {
  const r = await fetch('/api/runs').then(x => x.json());
  const picker = document.getElementById('picker');
  picker.innerHTML = '';
  for (const run of r.runs) {
    const o = document.createElement('option');
    o.value = run.dir_name;
    o.textContent = run.dir_name + '  -  ' + run.decision;
    picker.appendChild(o);
  }
  if (r.runs.length && !current) selectRun(r.runs[0].dir_name);
}

function selectRun(dir) {
  current = dir;
  document.getElementById('picker').value = dir;
  poll();
}

async function poll() {
  if (!current) return;
  const run = await fetch('/api/run?dir=' + encodeURIComponent(current)).then(x => x.json());
  render(run);
  clearTimeout(timer);
  if (run.live) {
    document.getElementById('status').textContent = 'live - running...';
    timer = setTimeout(poll, 1500);
  } else {
    document.getElementById('status').textContent = 'complete';
  }
}

function card(s, extraClass) {
  const points = (s.points || []).map(p => '<li>' + escapeHtml(p) + '</li>').join('');
  return '<div class="card ' + (extraClass || '') + '">'
    + '<h3>' + escapeHtml(s.title) + '</h3>'
    + '<p class="role">' + escapeHtml(s.role || '') + '</p>'
    + (s.summary ? '<p class="summary">' + escapeHtml(s.summary) + '</p>' : '')
    + (points ? '<ul>' + points + '</ul>' : '')
    + '</div>';
}

function render(run) {
  const html = (run.stages || []).map(s => card(s)).join('')
    + card(run.decision, 'decision');
  document.getElementById('cards').innerHTML = html;
}

function escapeHtml(t) {
  return String(t).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

document.getElementById('picker').addEventListener('change', e => selectRun(e.target.value));
document.getElementById('runNow').addEventListener('click', async () => {
  document.getElementById('status').textContent = 'starting...';
  const r = await fetch('/api/run-now', { method: 'POST' }).then(x => x.json()).catch(() => ({}));
  if (r.dir) { await loadRuns(); selectRun(r.dir); }
  else document.getElementById('status').textContent = r.error || 'could not start';
});

loadRuns();
</script>
```

- [ ] **Step 2: Write the entry point**

```python
# tradeloop/dashboard/__main__.py
from __future__ import annotations

import webbrowser
from http.server import HTTPServer
from pathlib import Path

from tradeloop.dashboard.server import make_handler

ROOT = Path(__file__).resolve().parents[1]  # tradeloop/
RUNS_DIR = ROOT / "runs"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def main(port: int = 8765) -> None:
    handler = make_handler(RUNS_DIR, STATIC_DIR)
    server = HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"TradeLoop dashboard at {url}  (Ctrl-C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Manual smoke test**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m tradeloop.dashboard`
Expected: browser opens to the dashboard; the newest existing run's cards render; the dropdown lists past runs. (Run-now button will error until Task 6 - that's fine.) Ctrl-C to stop.

- [ ] **Step 4: Commit**

```bash
git add tradeloop/dashboard/static/index.html tradeloop/dashboard/__main__.py
git commit -m "dashboard: the page + one-command entry point"
```

---

### Task 6: The "Run now" button (`POST /api/run-now`)

**Files:**
- Modify: `tradeloop/dashboard/server.py` (add POST handling + launcher)
- Test: `tradeloop/tests/dashboard/test_run_now.py`

**Interfaces:**
- Consumes: `make_handler` internals from Task 4.
- Produces: `launch_propose(repo_root: Path, python: str, launcher=subprocess.Popen) -> str` - starts a background propose cycle on the Claude backend with `ZERODHA_ENABLE_DATA=true`. The child mints its own run-dir name, so this returns `""` and the page just reloads the run list to pick up the newest folder. The `launcher` seam lets tests inject a fake so no real subprocess/LLM runs. `repo_root` is the git root (where `tradeloop` is importable as a package), used as the child's cwd.

- [ ] **Step 1: Write the failing test**

```python
# tradeloop/tests/dashboard/test_run_now.py
import os
from pathlib import Path

from tradeloop.dashboard.server import launch_propose


def test_launch_propose_invokes_claude_backend_with_data_on():
    captured = {}

    def fake_launcher(cmd, env=None, **kw):
        captured["cmd"] = cmd
        captured["env"] = env
        return object()

    launch_propose(Path("/tmp/x"), python="python3", launcher=fake_launcher)
    cmd = captured["cmd"]
    assert "tradeloop.orchestrator" in " ".join(cmd)
    assert "premarket" in cmd
    assert "--backend" in cmd and "claude" in cmd
    assert captured["env"]["ZERODHA_ENABLE_DATA"] == "true"
    # must NOT enable live trading
    assert captured["env"].get("ZERODHA_ENABLE_TRADING", "false") != "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_run_now.py -q`
Expected: FAIL - `ImportError: cannot import name 'launch_propose'`

- [ ] **Step 3: Write minimal implementation**

Add to `tradeloop/dashboard/server.py`:

```python
import os
import subprocess
import sys


def launch_propose(repo_root: Path, python: str = sys.executable, launcher=subprocess.Popen) -> str:
    """Start a background PROPOSE cycle on the Claude backend. Suggestions only -
    never routes. Returns "" (the run-dir name is minted inside the child; the
    page just reloads the run list to pick up the newest). `repo_root` is the git
    root (cwd for the child so `tradeloop` imports as a package)."""
    env = dict(os.environ)
    env["ZERODHA_ENABLE_DATA"] = "true"
    env.setdefault("ZERODHA_ENABLE_TRADING", "false")
    cmd = [python, "-m", "tradeloop.orchestrator", "premarket", "--backend", "claude"]
    launcher(cmd, env=env, cwd=str(Path(repo_root)))
    return ""
```

Then extend the handler in `make_handler` with a `do_POST`:

```python
        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/run-now":
                try:
                    launch_propose(runs_dir.parent.parent)  # tradeloop/runs -> tradeloop -> repo root
                    return self._json(200, {"started": True, "dir": ""})
                except Exception as exc:  # surface, don't crash the server
                    return self._json(500, {"error": str(exc)})
            self._json(404, {"error": "not found"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/ -q`
Expected: PASS (all dashboard tests)

- [ ] **Step 5: Update the page's run-now handler**

In `index.html`, the run-now click already reloads the run list. Change it to select the newest run after a short delay so the live poll picks up the fresh run folder:

```javascript
document.getElementById('runNow').addEventListener('click', async () => {
  document.getElementById('status').textContent = 'starting run...';
  const r = await fetch('/api/run-now', { method: 'POST' }).then(x => x.json()).catch(() => ({}));
  if (r.error) { document.getElementById('status').textContent = r.error; return; }
  setTimeout(async () => { await loadRuns(); const p = document.getElementById('picker'); if (p.value) selectRun(p.value); }, 2500);
});
```

- [ ] **Step 6: Commit**

```bash
git add tradeloop/dashboard/server.py tradeloop/dashboard/static/index.html tradeloop/tests/dashboard/test_run_now.py
git commit -m "dashboard: Run-now launches a propose cycle on the Claude backend"
```

---

### Task 7: End-to-end verification against a real run folder

**Files:**
- Test: `tradeloop/tests/dashboard/test_render_real_sample.py`

**Interfaces:**
- Consumes: everything above. Guards against schema drift by rendering a captured real run's stage files.

- [ ] **Step 1: Capture a real sample**

Copy the `.json` stage files from the newest folder under `tradeloop/runs/` that has a `41_pm_decision.json` into `tradeloop/tests/dashboard/sample_run/` (news, sentiment, fundamentals, technical, shortlist, bull, bear, debate, trade_plan, risk_report, pm_decision, orders). If none exists, generate one first with a propose cycle.

- [ ] **Step 2: Write the test**

```python
# tradeloop/tests/dashboard/test_render_real_sample.py
from pathlib import Path

from tradeloop.dashboard.runs import read_run

SAMPLE = Path(__file__).parent / "sample_run"


def test_real_sample_renders_without_raw_enums_or_crashes():
    out = read_run(SAMPLE)
    blob = " ".join(s["summary"] + " ".join(s["points"]) for s in out["stages"])
    # raw enum tokens must have been translated, not shown to the user
    for raw_token in ("bullish_entry", "tradeable", '"ticker"', "composite_score"):
        assert raw_token not in blob
    assert out["decision"]["summary"]
```

- [ ] **Step 3: Run + confirm**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/ -q`
Expected: PASS. Then run the full suite to confirm nothing else broke:
`/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q`

- [ ] **Step 4: Commit**

```bash
git add tradeloop/tests/dashboard/test_render_real_sample.py tradeloop/tests/dashboard/sample_run/
git commit -m "dashboard: end-to-end render check against a real run sample"
```

---

## Self-Review Notes

- **Spec coverage:** live monitoring (Task 5 polling + `live` flag Task 3), past runs (dropdown Task 5 + `list_runs` Task 3), plain-English cards for every stage (Tasks 1-2), glossary (Task 1 - the page tooltip wiring is a small follow-up if desired; terms ship in `GLOSSARY`), Run-now on Claude backend, suggestions only (Task 6), read-only + no-deps + no-AI-cost (Global Constraints, enforced by construction), error handling for missing/malformed files (Task 3 `_load`, Task 5 waiting state).
- **Deferred (matches spec "not in v1"):** approve/place buttons, login, mobile, P4 card, websockets.
- **Known small follow-up:** the `GLOSSARY` ships in Task 1 but wiring hover-tooltips into the HTML is left as a lightweight enhancement (highlight known terms in `escapeHtml` output). Flagged so it is not silently dropped.
