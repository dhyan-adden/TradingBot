from __future__ import annotations

from dataclasses import dataclass, field

from tradeloop.lib.llm.routing import model_for


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


# raw OpenRouter slug -> friendly label shown on the card
MODEL_LABELS: dict[str, str] = {
    "minimax/minimax-m3": "MiniMax M3",
    "xiaomi/mimo-v2.5": "MiMo v2.5",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "tencent/hy3-preview": "Tencent HY3",
}


def model_label(stage: str) -> str:
    slug = model_for(stage)
    return MODEL_LABELS.get(slug, slug)


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
    return StageView(stage="41_pm_decision", icon=icon, title=title, role=role,
                     summary=summary, points=points, model=model_label("41_pm_decision"))


_ANALYSIS_BUILDERS["30_trade_plan"] = _trade_plan
_ANALYSIS_BUILDERS["40_risk_report"] = _risk


def render_stage(stage: str, raw: dict) -> StageView:
    icon, title, role = _meta(stage)
    raw = raw or {}
    builder = _ANALYSIS_BUILDERS.get(stage)
    if builder is not None:
        summary, points = builder(raw)
    else:
        # Task 2 fills 30/40/41; until then, and for any unknown stage, a generic card.
        summary, points = "", []
    return StageView(stage=stage, icon=icon, title=title, role=role, summary=summary,
                     points=points, model=model_label(stage))
