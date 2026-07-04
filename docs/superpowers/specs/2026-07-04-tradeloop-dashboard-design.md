# TradeLoop Dashboard - Design Spec

Date: 2026-07-04

## Purpose

A local, read-only web dashboard that lets a non-technical, non-financial user **watch a morning TradeLoop run happen live** - each expert's output appearing on screen as it completes - and **browse past runs**, all translated into plain English with hover-to-explain jargon.

It is a window for understanding, not a control panel.
The deeper analysis, the buy/sell decision, and placing the trade happen in the Claude Code conversation plus the existing approve step - not in the dashboard.

## Where it sits in the operating loop

```
Dashboard (watch & understand)
      -> Claude Code chat (Claude reviews via review-trade + user and Claude decide)
      -> approve / route  (places the trade; paper now, real only past the promotion gate)
```

The dashboard covers only the first box.
Runs are executed on the **Claude backend** (the user's Claude subscription), not the OpenRouter models.

## Users and constraints

- Single non-technical user, running locally on their Mac.
- Must start with one simple command and open in the browser automatically.
- No new dependencies (Python standard library only); runs in the existing conda env.
- No per-view AI cost - translations are deterministic templates plus a glossary.
- Strictly read-only over run data: it never edits a run, never approves or places a trade.
- The single exception is the "Run now" button, which only launches a **propose** cycle (suggestions, no money).

## What it shows

For each run (live or historical), one friendly card per stage, in order:

Scan (`02_setups_raw`), News (`10`), Sentiment (`11`), Fundamentals (`12`), Technicals (`13`), Shortlist (`14`), Bull (`20`), Bear (`21`), Debate (`22`), Trade Plan (`30`), Risk (`40`), Decision (`41` + `orders.json`), and a Fills summary if the run was routed.

Each card has: an icon, the expert's name, a one-line "what this expert does," and a plain-English summary of its output.
The summary surfaces the bot's own prose where it exists (the thesis / notes / reason fields) and adds templated translation of the structured bits (scores, verdicts, tickers -> company names).
Finance and technical terms are highlighted with hover tooltips drawn from a glossary.

The final **Decision** card states, in plain English, either:
"Proposing to BUY <company> at <price>, because ..." or "Holding today - nothing convincing," pulled from the PM decision plus `orders.json`.

## The flow

1. Open the dashboard (one command).
2. Click **Run now** -> starts a real morning run on the Claude backend (the user's subscription); suggestions only, no money.
3. Cards fill in live as each expert finishes (the browser polls the run folder about every 1.5 seconds).
4. The run ends on the Decision card.
5. Alternatively, pick a past date from a dropdown and re-read any run the same way.

## Architecture (small, independently testable units)

- `render.py` (pure, no I/O): turns a raw stage dict/text into a `StageView` = {icon, title, role_line, summary, points, terms}. Also holds `GLOSSARY`: term -> plain explanation. Fully unit-testable.
- `runs.py`: list run folders, read a run's stage files into raw dicts, decide whether a run is live (still being written) or complete.
- `server.py`: standard-library `http.server`. Routes:
  - `GET /` - the page.
  - `GET /api/runs` - list of runs (date, mode, decision one-liner).
  - `GET /api/run?dir=...` - one run's `StageView`s plus a live/complete status.
  - `POST /api/run-now` - launch `run_cycle` with `backend=claude` and `ZERODHA_ENABLE_DATA=true` as a background subprocess; return the new run folder. This is the only route that writes anything, and it only starts a propose cycle.
- `static/index.html`: one page, inline CSS and JS. Renders cards from `/api/run`, polls while a run is live, has the Run-now button, the history dropdown, and the glossary tooltips. No framework.
- `__main__.py`: start the server on a local port and open the browser. Entry point for `python -m tradeloop.dashboard`.

## Data flow

Browser -> `GET /api/run?dir=<newest or selected>` -> server reads the run folder's stage files -> `render.py` turns each into a `StageView` -> JSON -> browser renders or updates the cards.
While a run is live, the browser re-polls; newly written stage files become new cards.
Run-now -> subprocess -> a new run folder -> the browser follows it live.

## Error handling

- A missing or not-yet-written stage file: show the card as "waiting..." during a live run, or skip it for a historical run. Never crash.
- A malformed stage file: show a gentle "couldn't read this step" card and keep going.
- Run-now while the market is closed (weekend / holiday) or the Zerodha login has expired: the cycle itself reports this, and the dashboard surfaces the friendly message ("market closed today" / "market login expired - run the login step").
- The server is localhost-only and single-user; no authentication.

## Testing

- `render.py`: unit tests feeding representative stage outputs (real samples copied from an existing run folder) and asserting the friendly summary, the key points, and that known jargon is tagged. Cover both a propose run and a hold (no-order) run.
- `runs.py`: list and read against a temporary folder of fixture stage files; test live-vs-complete detection.
- `server.py`: a light smoke test - drive the handler, `GET /api/run` on a fixture run folder, assert the JSON shape; assert that run-now is the only writing route and is not triggered by the read paths.

## Not in v1 (deliberately out of scope)

- No approve / place-trade buttons - that stays in the chat plus the approve step.
- No login or accounts, no mobile app, no websockets (polling is enough for a few-minute run).
- No P4 "report card" card yet - added once P4 exists.
- No editing or annotating runs.

## Dependencies and assumptions

- The Claude backend (`claude -p`, the `.claude/agents/tradeloop-*` subagents) is installed and logged in on the user's machine, and writes the same numbered stage artifacts into the run folder as each subagent completes - which is what makes live monitoring possible.
- A valid daily Zerodha token is present for the scan; if not, the run degrades to no setups and the dashboard shows that plainly.
