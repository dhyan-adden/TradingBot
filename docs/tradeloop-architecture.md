# TradeLoop architecture — in plain English

**Date:** 2026-07-02
**Purpose:** explain what the re-architected TradeLoop is, why each piece exists, and what each piece does — first in plain English, then as the exact module layout and interfaces the five phase plans build against.

---

## 1. What this is, in one paragraph

TradeLoop is an automated Indian-stock **swing-trading research loop**. Once or twice a day it gathers real news and price data, has a team of AI "analysts" argue about which stocks look good, turns the winners into concrete buy/sell orders, checks those orders against hard risk rules **in code**, and either simulates them (paper) or — much later, once it has proven itself — places them live through the broker. Every input it read and every decision it made is written down so you can audit it afterwards. The aim is to eventually trust it with real money and make a profit; the whole design exists to earn that trust before risking a rupee.

## 2. The two problems we are fixing

Today TradeLoop looks finished but has two hollow spots:

1. **It reasons over nothing.** The step that is supposed to fetch news and price setups writes *empty* files, so the AI analysts are guessing in the dark.
2. **Its safety rules are switched off.** There is a written risk gate — the code that says "reject an order that's too big / breaks the rules" — but nothing ever calls it. Orders can go out unchecked.

Everything below is about filling those two holes: **make the inputs real and auditable, and make the rules impossible to bypass.**

## 3. The moving parts, each explained simply

Think of a cycle like a small trading desk running for one morning. Here is each role.

- **The orchestrator — the desk manager.** One Python program that runs the whole cycle start to finish: decides whether today is even a trading day, calls each analyst in order, hands the final orders to the compliance check, and writes the summary. Today this job is done by a fragile shell script that hands off to an external tool; we replace it with one Python program that owns the flow.

- **The settings file — the rulebook.** One file (`settings.yaml`) that holds every number the desk obeys: how much capital, the biggest position allowed, how many positions at once, the daily loss limit, the costs, and the bar a strategy must clear before it's allowed to trade live. Everyone reads from this one rulebook so the numbers can't drift apart.

- **The gates — the bouncer at the door.** Three quick yes/no checks before any work happens: *Is it a market holiday?* *Has someone pulled the kill-switch?* *If we're in live mode, have we actually earned the right to trade live?* Any "no" stops the cycle cold. Right now these checks are calculated and then ignored; we make them actually stop the cycle.

- **The 13 analysts — the research team.** A pipeline of AI roles: news, sentiment, fundamentals, technicals, a shortlister, a bull and a bear who argue, a moderator who scores the debate, a trader who writes the ticket, a risk manager, and a portfolio manager who signs off. Each reads the previous one's output and writes its own. These are markdown prompts today; we keep the *roles* but drive them from Python calling the model directly (through OpenRouter), and we make each one fill in a **structured form** instead of free text.

- **The structured forms — filling in a form instead of writing an essay.** Instead of an analyst writing a paragraph we hope to parse, each one returns a validated object (a shortlist entry, a trade ticket, a debate verdict, an order). If the form is malformed, the cycle stops loudly instead of guessing. This is what makes decisions machine-checkable.

- **The news wire and the ticker — the data backbone.** Two kinds of real input: **news** (Google News, Indian financial RSS, official NSE/BSE announcements, Reddit) fetched over a hardened connection, de-duplicated, and tagged to the right stock; and **price** (last price, daily candles, history) pulled from **Kite**, the broker's own data. Every fetched item gets a short **news_id** so decisions can cite it.

- **The frozen snapshot — the sealed evidence box.** At the start of each cycle we freeze exactly what was fetched into a per-cycle folder and hash it. That means we can re-run the cycle later and it reads the *same* inputs — "input-reproducibility." No quietly changing data under the decision.

- **The evidence trailer — the citations.** When an analyst recommends a stock, it must attach the `news_id`s it relied on. Code then checks every cited id actually exists in that cycle's snapshot. A claim with no evidence in the box is rejected.

- **The risk gate (`evaluate()`) — the compliance officer.** A pure piece of Python that takes one proposed order plus the current portfolio and the rulebook, and returns approved / rejected-with-reasons. It checks the order is in our universe, long-only, not too big, not the 5th position, not over the sector cap, not selling more than we hold, and so on. **Every order passes through this before anything routes.** This is the switched-off gate we turn on.

- **The paper broker and the book — the practice trading account.** In paper mode (the default, and where we live for a long time), orders "fill" in a simulator that models real Indian costs and slippage. The **book** is the running record of what we hold and how much cash is left; it persists between cycles, so tomorrow's cycle knows what today bought. Without a persisted book, the desk forgets its positions every morning (which is why selling is currently broken).

- **The audit ledger — the flight recorder.** An append-only, tamper-evident log (SQLite, each row hash-linked to the last) of *everything*: every fetch (success and failure), every model call, every risk verdict, every fill. Positions and profit are *derived* by replaying this log, so the record and the reality can't disagree. This is how "every decision is accountable" becomes true.

- **The reconciler, controls, and attribution — the auditor.** After trading: recompute positions two independent ways and flag any mismatch (reconcile); independently re-run the risk rules over what actually happened and confirm nothing slipped through (controls); and compare the profit we *expected* from each trade to what we *got*, in units of risk "R" (attribution). This is bookkeeping-grade accountability without full double-entry accounting.

- **The broker line (Kite MCP) — the phone to the exchange.** A small local server that speaks to Zerodha/Kite for both price data and (eventually) live orders. It is deliberately gated: it refuses to place a real order unless live trading is explicitly switched on. It is the one integration that already works and that we keep.

## 4. How one cycle flows, end to end

1. The **orchestrator** starts for a mode (`premarket`, `intraday`, or `postclose`).
2. The **gates** check holiday / kill-switch / live-readiness. Any block → stop.
3. It takes a **global lock** (so two cycles never run at once) and starts a timeout.
4. The **data backbone** fetches news + price, tags them, and freezes a **snapshot** with `news_id`s. Every fetch is logged to the **ledger**.
5. The **13 analysts** run in order, each reading the snapshot and prior outputs, each returning a **structured form** with an **evidence trailer**. Code checks every cited `news_id` is in the snapshot.
6. The portfolio manager's output becomes **orders**. Python (not the AI) turns them into order tickets.
7. Each order passes the **risk gate**. Approved orders route to the **paper broker**; the **book** updates; rejected orders are logged with reasons.
8. The **ledger** records every verdict and fill. Positions/P&L come from replaying it.
9. On `postclose`, the **auditor** reconciles, control-tests, and attributes performance, and the learning notes feed tomorrow.

Paper is the default throughout. Live is only ever reached after the strategy clears the promotion bar in the rulebook, and even then every order still passes the same risk gate.

## 5. Target module layout (the shared spine)

The five phase plans all build against this structure. `keep` = exists and stays, `wire` = exists but must be connected, `new` = created, `rewrite` = exists but rebuilt.

```
tradeloop/
  orchestrator.py            new (P0)  desk manager: gates→lock→prepare→reason→order-path
  lib/
    config.py                new (P0)  typed Settings + risk_caps()
    broker/
      paper_broker.py         keep      OrderTicket/Fill/Side, place_order (the sim)
      paper_book.py           new (P0)  hydrate()/append() persisted book (→ ledger in P2)
      orders_schema.py        new (P0)  Order/OrdersFile typed; load_orders()
      router.py               rewrite   route_orders_file(): gate every order + route
      cost_model.py           keep      India cost math
      zerodha_mcp.py          keep      live order payload builder
    risk/
      checks.py               wire      evaluate() gate + RiskState/RiskCaps/RiskDecision
      sizing.py               wire      position sizing
      circuit_breaker.py      keep      kill_switch_active()
    llm/                       new (P1)
      client.py                         OpenRouter call_json (role→model, retry, usage, audit)
      routing.py                        model-per-stage table (real IDs)
      stages.py                         run one stage: prompt + schema → validated output
      schemas.py                        pydantic per-stage outputs + evidence trailer
    audit/                     new (P2)
      ledger.py                         append-only hash-chained SQLite; replay/project
      reconcile.py             (P4)     positions two ways
      controls.py              (P4)     re-run rules over actuals
      attribution.py           (P4)     expected vs realized R
    data/                      (P3 unless noted)
      http.py                           hardened HTTP (UA/retry/backoff/timeout/conditional GET)
      ingest.py                         fetch orchestrator → snapshot
      snapshot.py                       freeze + hash + news_id
      tickers.py                        word-boundary matching over ticker_master
      ticker_master.py         keep      symbol/alias/ISIN master (add ISIN index)
      sentiment.py                      deterministic sentiment
      kite.py                  new       Kite MCP client: ltp/ohlc/historical (price backbone)
      sources/
        google_news.py         rewrite   hardened Google News
        rss_native.py          new       Moneycontrol/ET/Mint/BS
        nse_bse.py             new       official announcements
        reddit.py              rewrite   tier-C social
      news_to_tickers.py       wire      keep renderer + schema; matching moves to tickers.py
    portfolio/
      state.py                 wire      PortfolioState + render_context (hydrate real book)
    ta/  indicators.py keep · patterns.py keep · scanner.py rewrite (wire, kill silent-except)
    memory/ writer.py · retriever.py · dossier.py   refactor (P4 learning + provenance)
    util/ ist_clock.py · holidays.py   wire (populate holidays; one clock)
  config/*.yaml                keep      settings/universe/indicators/strategy_families/news_sources
  prompts/*.md                 keep      13 roles + shared (edit: agent stops at orders.json)
  state/                       new       paper_book.jsonl (P0) → ledger.db (P2)
pyproject.toml                 rewrite   package tradeloop; declare pyyaml, pandas; drop langgraph later
```

## 6. Key interfaces (pinned so the phases agree)

```python
# config (P0)
load_settings(path: Path) -> Settings
risk_caps(settings: Settings, universe: Iterable[str], capital_inr: float) -> RiskCaps

# risk gate (exists — wired P0)
evaluate(ticket: OrderTicket, state: RiskState, caps: RiskCaps) -> RiskDecision

# orders (P0)
load_orders(path: Path) -> OrdersFile            # {mode, live_orders_enabled, orders:[Order], held:[Order]}
to_ticket(order: Order) -> OrderTicket

# paper book (P0; body swapped in P2)
paper_book.hydrate(path: Path, starting_cash_inr: float) -> PaperBroker
paper_book.append(path: Path, fills: list[Fill]) -> None

# order path (P0)
route_orders_file(orders_path, fills_path, book: PaperBroker, settings: Settings, root) -> list[RoutedOrder]

# reasoning (P1)
llm.client.call_json(role: str, system: str, user: str, schema: type[BaseModel]) -> BaseModel
stages.run_stage(name: str, run_dir: Path) -> BaseModel      # loads prompt + inputs, validates output

# audit ledger (P2)
ledger.append(event: dict) -> str                            # returns row hash (chained to prev)
ledger.replay(types: list[str] | None = None) -> list[dict]
ledger.project_positions() -> PaperBroker                    # replaces paper_book.hydrate body

# data backbone (P3)
kite.ltp(symbols: list[str]) -> dict[str, float]
kite.ohlc(symbol: str) -> dict
kite.historical(symbol: str, frm: date, to: date, interval: str) -> list[Candle]
ingest.run(as_of: datetime, symbols: list[str], max_fetch: int) -> Snapshot
snapshot.freeze(items, run_dir) -> tuple[Path, str]          # (snapshot dir, snapshot_hash)
tickers.extract(items, master: TickerMaster) -> list[TaggedStory]
news_id(guid: str, url: str, title: str) -> str              # sha256(guid|url|title)[:12]

# finance controls (P4)
reconcile.compare(book, ledger, kite_holdings=None) -> list[Delta]
controls.recheck(orders: OrdersFile, fills: list[dict], caps: RiskCaps, state: RiskState) -> ControlReport
attribution.report(trade_plans, fills) -> StrategyPerformance
```

## 7. The five phases and why this order

Safety before data — nothing routes unguarded, then the inputs become real.

| Phase | Plain-English purpose | Fills DoD |
|---|---|---|
| **P0 — orchestrator + safety gate** | Build the desk manager and switch on the compliance officer, so every order is checked. Fix packaging. | #4 |
| **P1 — reasoning layer** | Have Python call the models directly and make each analyst fill in a validated form; record model + response. | #3 (half) |
| **P2 — audit ledger** | Add the flight recorder; derive positions/P&L from it; log every fetch. | #2 |
| **P3 — data backbone** | Make inputs real: Kite price + four news sources, snapshot, `news_id`, evidence trailer checked against the snapshot. | #1, #3 (half) |
| **P4 — finance controls** | The auditor: reconcile, control-test, attribute performance, learn. | polish |

Definition of done is met when P3 lands (real, auditable inputs + enforced rules); P4 is the accountability layer on top.
