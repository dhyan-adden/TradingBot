from __future__ import annotations

import re
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
    model: str = ""


# raw provider slug -> friendly label shown on the card. Legacy OpenRouter runs
# still render with their true historical model; claude:* is formatted inline.
MODEL_LABELS: dict[str, str] = {
    "minimax/minimax-m3": "MiniMax M3",
    "xiaomi/mimo-v2.5": "MiMo v2.5",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "tencent/hy3-preview": "Tencent HY3",
}


def label_model(slug: str) -> str:
    """Friendly label for the model that ACTUALLY ran a stage (read from the run's
    llm_calls.jsonl), not a guess from the routing config - so the badge stays
    honest across a backend swap. Empty when no call was recorded yet."""
    if not slug:
        return ""
    if slug.startswith("claude:"):
        return "Claude " + slug.split(":", 1)[1].capitalize()
    if slug.startswith("codex:"):
        model = slug.split(":", 1)[1]
        return "Codex / " + MODEL_LABELS.get(model, model)
    return MODEL_LABELS.get(slug, slug)


# stage -> (icon, friendly name, one-line "what this expert does")
STAGE_META: dict[str, tuple[str, str, str]] = {
    "10_news": ("news", "News Expert", "Reads the morning's headlines and finds stocks with a story behind them."),
    "11_sentiment": ("chat", "Mood Expert", "Gauges how retail traders and social media feel about each stock."),
    "12_fundamentals": ("book", "Health Expert", "Checks each company's financial health for red flags."),
    "13_technical": ("chart", "Chart Expert", "Reads the price charts to spot clean, tradeable setups."),
    "14_shortlist": ("list", "Shortlister", "Combines every expert's view into today's ranked list of candidates."),
    "15_holdings_review": ("shield", "Position Manager", "Reviews every holding: keep it, tighten the stop, trim, or exit."),
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
    points = [f"{pretty_ticker(n.get('ticker',''))}: {n.get('catalyst','')} (tier {n.get('tier','?')})"
              for n in names]
    summary = macro or (f"{len(points)} name(s) with a story today."
                        if points else "No fresh stock-specific news today.")
    if not points:
        points = ["No fresh stock-specific news stood out today."]
    return summary, points


def _sentiment(raw: dict) -> tuple[str, list[str]]:
    scores = raw.get("scores") or []
    points, pos, neg = [], 0, 0
    for s in scores:
        val = s.get("sentiment_score", 0)
        if val > 0.15:
            pos += 1
        elif val < -0.15:
            neg += 1
        mood = "positive" if val > 0.15 else "negative" if val < -0.15 else "neutral"
        echo = " (looks like echo-chamber buzz)" if s.get("echo_chamber_flag") else ""
        points.append(f"{pretty_ticker(s.get('ticker',''))}: {mood} mood{echo}")
    summary = (f"{len(points)} name(s): {pos} positive, {neg} negative." if points
               else "No notable social buzz.")
    return summary, points


def _fundamentals(raw: dict) -> tuple[str, list[str]]:
    tags = raw.get("tags") or []
    points, flagged = [], 0
    for t in tags:
        if t.get("tag") in ("yellow", "red"):
            flagged += 1
        flags = ", ".join(t.get("red_flags") or [])
        extra = f" - {flags}" if flags else ""
        points.append(f"{pretty_ticker(t.get('ticker',''))}: {_TAG.get(t.get('tag'), t.get('tag',''))}{extra}")
    summary = (f"{len(points)} checked, {flagged} with concerns." if points
               else "No fundamentals flagged.")
    return summary, points


def _technical(raw: dict) -> tuple[str, list[str]]:
    setups = raw.get("setups") or []
    points, confirmed = [], 0
    for s in setups:
        if s.get("news_confirmed"):
            confirmed += 1
        cls = _CLASSIFY.get(s.get("classification"), s.get("classification", ""))
        backed = " (news backs it up)" if s.get("news_confirmed") else ""
        note = f" - {s.get('notes')}" if s.get("notes") else ""
        points.append(f"{pretty_ticker(s.get('ticker',''))}: {cls}{backed}{note}")
    summary = (f"{len(points)} clean setup(s), {confirmed} news-backed." if points
               else "No clean chart setups today.")
    return summary, points


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
    summary = (f"{lead} {len(points)} name(s)." if points else f"{lead} nothing to argue today.")
    return summary, points


def _verdict_line(n: dict) -> str:
    verdict = str(n.get("verdict", ""))
    return (f"{pretty_ticker(n.get('ticker',''))}: {_VERDICT.get(verdict, verdict)} "
            f"(conviction {n.get('conviction','?')}/10)"
            + (f" - {n['rationale']}" if n.get("rationale") else ""))


def _debate_summary(names: list[dict]) -> str:
    tradeable = [n for n in names if n.get("verdict") == "tradeable"]
    return (f"{len(tradeable)} name(s) green-lit to trade." if tradeable
            else "Cautious today - nothing green-lit to trade.")


def _debate(raw: dict) -> tuple[str, list[str]]:
    names = raw.get("names") or []
    points = [_verdict_line(n) for n in names]
    return _debate_summary(names), (points or ["No names debated."])


def _claims_by_ticker(case: dict | None) -> dict[str, list[str]]:
    claims: dict[str, list[str]] = {}
    for a in ((case or {}).get("arguments") or []):
        claims.setdefault((a.get("ticker") or "").upper(), []).append(a.get("claim", ""))
    return claims


def render_debate(raw: dict, bull: dict | None = None, bear: dict | None = None,
                  model: str = "") -> StageView:
    """The Judge's card with the complete recorded exchange: each name's verdict
    followed by the bull's and bear's claims for it, in the judge's order."""
    icon, title, role = _meta("22_debate")
    names = (raw or {}).get("names") or []
    bull_by, bear_by = _claims_by_ticker(bull), _claims_by_ticker(bear)
    points: list[str] = []
    for n in names:
        t = (n.get("ticker") or "").upper()
        points.append(_verdict_line(n))
        points += [f"For: {c}" for c in bull_by.get(t, [])]
        points += [f"Against: {c}" for c in bear_by.get(t, [])]
    return StageView(stage="22_debate", icon=icon, title=title, role=role,
                     summary=_debate_summary(names),
                     points=points or ["No names debated."], model=label_model(model))


_ANALYSIS_BUILDERS = {
    "10_news": _news, "11_sentiment": _sentiment, "12_fundamentals": _fundamentals,
    "13_technical": _technical, "14_shortlist": _shortlist,
    "20_bull": lambda r: _args(r, "The case FOR buying:"),
    "21_bear": lambda r: _args(r, "The case AGAINST:"),
    "22_debate": _debate,
}


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
    points, counts = [], {"approve": 0, "resize": 0, "reject": 0}
    for r in rows:
        d = r.get("decision")
        if d in counts:
            counts[d] += 1
        q = r.get("resized_quantity")
        qty = f" to {q} shares" if d == "resize" and q is not None else ""
        why = ("; ".join(r.get("reasons") or []))
        points.append(f"{pretty_ticker(r.get('ticker',''))}: {_RISK.get(d, d or '')}{qty}"
                      + (f" - {why}" if why else ""))
    summary = (f"{counts['approve']} approved, {counts['resize']} resized, {counts['reject']} rejected."
               if points else "No plans reached the risk check.")
    return summary, points


def render_decision(orders_json: dict, model: str = "",
                    fills: list | None = None) -> StageView:
    """Render the PM decision card.

    fills=None means no fills.json yet (human-in-loop pending, or conviction-blocked
    before route_cycle was called). fills=[] or a list means route_cycle ran.
    """
    icon, title, role = _meta("41_pm_decision")
    orders = (orders_json or {}).get("orders") or []

    if not orders:
        summary = "Holding today - nothing convincing enough to propose."
        points: list[str] = []
    elif fills is not None:
        # route_cycle was called (auto mode); summarise by what actually happened
        filled = [f for f in fills if f.get("status") == "FILLED"]
        rejected = [f for f in fills if f.get("status") == "RISK_REJECTED"]
        if filled:
            sym = (filled[0].get("payload") or {}).get("symbol") or orders[0].get("ticker", "?")
            qty = (filled[0].get("payload") or {}).get("quantity") or orders[0].get("quantity", "?")
            rej_note = f", {len(rejected)} risk-rejected" if rejected else ""
            summary = f"Auto-routed: {sym} \u00d7 {qty} shares filled ({len(filled)} filled{rej_note})."
        elif rejected:
            summary = f"Auto-routed but risk gate rejected all {len(rejected)} order(s)."
        elif not fills:
            summary = "Order proposed, but no route outcome was recorded."
        else:
            summary = f"Auto-routed: {len(orders)} order(s) processed."
        points = [f"{o.get('side','BUY')} {o.get('quantity','?')} {pretty_ticker(o.get('ticker',''))} "
                  f"@ {o.get('price','?')} - {o.get('reason','')}" for o in orders]
    else:
        # human-in-loop: orders proposed, awaiting approval
        first = orders[0]
        summary = (f"Proposing to {first.get('side','BUY')} {first.get('quantity','?')} shares of "
                   f"{pretty_ticker(first.get('ticker',''))} at {first.get('price','?')}.")
        points = [f"{o.get('side','BUY')} {o.get('quantity','?')} {pretty_ticker(o.get('ticker',''))} "
                  f"@ {o.get('price','?')} - {o.get('reason','')}" for o in orders]
    return StageView(stage="41_pm_decision", icon=icon, title=title, role=role,
                     summary=summary, points=points, model=label_model(model))


def _holdings_review(raw: dict) -> tuple[str, list[str]]:
    rows = raw.get("reviews") or []
    points = []
    for r in rows:
        extra = ""
        if r.get("new_stop") is not None:
            extra = f" new stop {r['new_stop']}"
        if r.get("exit_quantity") is not None:
            extra = f" sell {r['exit_quantity']}"
        points.append(f"{pretty_ticker(r.get('ticker',''))}: {r.get('verdict','')}"
                      f" ({r.get('reason_code','')}){extra} - {r.get('rationale','')}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("verdict", "?")] = counts.get(r.get("verdict", "?"), 0) + 1
    breakdown = ", ".join(f"{n} {v}" for v, n in sorted(counts.items()))
    summary = (f"{len(rows)} holdings reviewed: {breakdown}." if rows
               else "No holdings to review.")
    return summary, points


_ANALYSIS_BUILDERS["15_holdings_review"] = _holdings_review
_ANALYSIS_BUILDERS["30_trade_plan"] = _trade_plan
_ANALYSIS_BUILDERS["40_risk_report"] = _risk


def render_stage(stage: str, raw: dict, model: str = "") -> StageView:
    icon, title, role = _meta(stage)
    raw = raw or {}
    builder = _ANALYSIS_BUILDERS.get(stage)
    if builder is not None:
        summary, points = builder(raw)
    else:
        # Task 2 fills 30/40/41; until then, and for any unknown stage, a generic card.
        summary, points = "", []
    return StageView(stage=stage, icon=icon, title=title, role=role, summary=summary,
                     points=points, model=label_model(model))


def render_markdown_stage(stage: str, text: str, model: str = "") -> StageView:
    """Render Codex-written Markdown when the structured stage JSON is absent."""
    icon, title, role = _meta(stage)
    candidates: list[str] = []
    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            if line.startswith("## "):
                in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("Source track applied:") or line.startswith("Reads:"):
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if (not cells or all(set(cell) <= {"-", ":", " "} for cell in cells)
                    or ("ticker" in line.lower() and
                        any(word in line.lower() for word in ("score", "tag", "read")))):
                continue
            line = " - ".join(cells)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        if line:
            candidates.append(line)
    summary = candidates[0] if candidates else "No structured summary was written."
    points = candidates[1:13]
    return StageView(stage=stage, icon=icon, title=title, role=role,
                     summary=summary, points=points, model=label_model(model))
