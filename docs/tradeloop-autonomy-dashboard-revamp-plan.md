# TradeLoop Paper Autonomy And Dynamic Dashboard Revamp Plan

## Objective

Make TradeLoop operate as an autonomous paper-trading system with little to no human approval while keeping live trading blocked by default.
Revamp the dashboard from a run-picker artifact viewer into a modern dynamic operator website that explains what the bot is doing, why it is doing it, what gates passed or blocked, and what risk is currently open.

## Primary Assumptions

Paper autonomy is the immediate target.
Live routing must remain disabled unless a later explicit decision enables it.
The existing stdlib Python dashboard server should remain unless there is a hard need for a frontend framework.
The dashboard should feel like an actual modern web product, not a debug page.
The main dashboard should be dynamic and current-state driven.
Historical runs should move into a separate History tab.

## Non-Goals For This Batch

Do not place real Zerodha live orders automatically.
Do not add a database beyond the existing ledger and file artifacts.
Do not migrate the dashboard to React or Next.js in this batch.
Do not change trading strategy logic unless needed to make automation safe and transparent.
Do not inspect `.env` or print secret-like environment values.

## Existing System Facts

`tradeloop/orchestrator.py` already supports auto-routing when `execution.approval_mode` is `auto`.
`tradeloop/config/settings.yaml` currently sets `approval_mode: auto` and `allow_auto_live: true`.
`route_cycle` blocks live auto-routing only when `live_enabled()` is true, `approval_mode` is `auto`, and `allow_auto_live` is false.
`route_order` does not directly execute live Zerodha orders; it emits a `READY_FOR_CODEX_TOOL_CALL` payload when live routing is authorized.
The paper route path fills via `PaperBroker` and appends routed fills to `state/ledger.db`.
`dashboard/static/index.html` is currently a single static page that lists readiness, portfolio, transactions, and selected run cards.
`dashboard/server.py` already exposes `/api/runs`, `/api/run`, `/api/portfolio`, `/api/status`, `/api/route-paper`, and `/api/run-now`.
`dashboard/runs.py` already derives stage cards, decision summaries, model labels, usage, and cost from run artifacts.
`dashboard/status.py` already exposes kill switch, live env, live promotion, source health, and latest run state.
The README has unresolved merge conflict markers and stale human-in-loop language.
`cron_dispatch.sh` still comments that cycles are propose-only, even though config and tests expect auto-route.

## Target Operating Model

### Paper Mode

Premarket and intraday scheduled cycles run automatically.
If deterministic gates pass, eligible paper orders route automatically.
If gates fail, the run is blocked and the dashboard explains the exact blocker.
No manual approval is required for paper fills.
The kill switch halts all routing immediately.

### Live Mode

`allow_auto_live` should default to false.
Even if `ZERODHA_ENABLE_TRADING=true`, auto live routing should block with `AUTO_LIVE_DISABLED` unless the operator explicitly changes config later.
The dashboard should show live capability as a locked state, not as an active path.
Promotion, canary, reconciliation, and ledger gates should still be visible so readiness is transparent.

### Human Role

The user should review exceptions, not approve every paper action.
The user should use the dashboard to inspect blocks, drift, stale data, source failures, audit failures, and live-readiness gates.
Human approval remains available for live/human-in-loop modes but is not the default paper workflow.

## Phase 1: Clean Configuration And Automation Contract

### Files

`tradeloop/config/settings.yaml`
`tradeloop/lib/config.py`
`tradeloop/tests/test_config.py`
`tradeloop/tests/test_approval.py`
`tradeloop/tests/test_e2e_auto_route.py`

### Changes

Set `execution.allow_auto_live` to `false`.
Keep `execution.approval_mode: auto`.
Keep `execution.auto_route_min_conviction: 6.5`.
Remove or deprecate the duplicate top-level `live_promotion_gates` block because `lib/live/promotion.py` uses `execution.promotion` through the `Settings` dataclass.
If removing the duplicate would touch too many tests, keep it for now but add a comment that `execution.promotion` is authoritative and `live_promotion_gates` is legacy read-only compatibility.
Update `test_config.py` to expect `allow_auto_live is False`.
Keep tests that prove paper route ignores `allow_auto_live`.
Keep tests that prove live auto is blocked when `allow_auto_live` is false.

### Exit Criteria

`load_settings()` returns `approval_mode == "auto"`.
`load_settings()` returns `allow_auto_live is False`.
Paper auto-route tests still pass.
Live auto-route tests prove the route blocks before reconciliation when `allow_auto_live` is false.

### Verification

Run `python -m pytest tradeloop/tests/test_config.py tradeloop/tests/test_approval.py tradeloop/tests/test_e2e_auto_route.py`.

## Phase 2: Make Gate Outcomes First-Class Artifacts

### Files

`tradeloop/orchestrator.py`
`tradeloop/lib/broker/router.py`
`tradeloop/lib/risk/checks.py`
`tradeloop/tests/test_orchestrator.py`
`tradeloop/tests/test_e2e_auto_route.py`

### New Artifact

Add `gate_summary.json` in every run directory.
The artifact should be written during propose and updated during route.
It should contain deterministic, dashboard-ready records.

### Proposed Shape

```json
{
  "run_dir": "2026-08-26_0800_premarket",
  "mode": "premarket",
  "phase": "routed",
  "autonomy": {
    "approval_mode": "auto",
    "paper_auto_route": true,
    "live_env_enabled": false,
    "allow_auto_live": false
  },
  "gates": [
    {
      "id": "holiday",
      "label": "Market holiday",
      "status": "passed",
      "severity": "blocker",
      "detail": "NSE trading day"
    },
    {
      "id": "kill_switch",
      "label": "Kill switch",
      "status": "passed",
      "severity": "blocker",
      "detail": "kill_switch.md not active"
    },
    {
      "id": "evidence",
      "label": "Evidence citations",
      "status": "passed",
      "severity": "blocker",
      "detail": "all referenced evidence exists"
    },
    {
      "id": "conviction",
      "label": "Minimum conviction",
      "status": "passed",
      "severity": "blocker",
      "detail": "all BUY orders >= 6.5"
    },
    {
      "id": "route_risk",
      "label": "Route risk engine",
      "status": "passed",
      "severity": "blocker",
      "detail": "1 filled, 0 rejected"
    }
  ],
  "summary": "Auto-routed paper order after all required gates passed."
}
```

### Status Vocabulary

Use exactly these statuses: `passed`, `blocked`, `warning`, `skipped`, `not_applicable`, `unknown`.
Use exactly these severities: `blocker`, `warning`, `info`.
Never make the dashboard infer gate truth from prose logs if a structured artifact exists.

### Implementation Details

Add small helper functions in `orchestrator.py` rather than a new package initially.
Use `_append_gate(run_dir, id, label, status, severity, detail)` or a single `_write_gate_summary(run_dir, ...)` helper.
Call it at each existing gate branch: holiday, kill switch, live promotion, no holdings, orders invalid, evidence, price grounding, quality block, conviction, auto route, route result.
Do not change gate semantics in this phase.
Make the helper tolerant of missing or malformed existing summary files.
Write final `phase` values as one of `preparing`, `reasoning`, `awaiting_approval`, `auto_routing`, `routed`, `blocked`, `failed`.

### Exit Criteria

Every completed or blocked run has `gate_summary.json`.
The artifact explains blocks without parsing stdout.
Existing stdout messages remain for cron logs.

### Verification

Add a test that an auto-routed run writes `gate_summary.json` with conviction and route risk gates.
Add a test that a conviction-blocked run writes status `blocked` with the threshold reason.
Run `python -m pytest tradeloop/tests/test_orchestrator.py tradeloop/tests/test_e2e_auto_route.py`.

## Phase 3: Strengthen Paper Autonomy Safety Rules

### Files

`tradeloop/orchestrator.py`
`tradeloop/lib/config.py`
`tradeloop/config/settings.yaml`
`tradeloop/tests/test_cycle_guards.py`
`tradeloop/tests/data/test_grounding_wiring.py`

### New Config

Add this section under `execution`:

```yaml
  paper_autonomy:
    require_buy_evidence_snapshot: true
    require_buy_price_grounding: true
    allow_exits_without_snapshot: true
    allow_stop_tightens_without_snapshot: true
```

Expose it in `Settings` as four boolean fields.

### Behavior

In auto mode, any new BUY should block if no snapshot exists and `require_buy_evidence_snapshot` is true.
In auto mode, any new BUY should block if scanner levels are missing and `require_buy_price_grounding` is true.
SELL exits should still route when data is degraded.
Stop-tightens should still apply when data is degraded.
Human-in-loop mode may still allow review of ungrounded proposals, but the dashboard should mark that clearly.

### Rationale

The current code skips evidence and grounding when `snap is None` or `scan_levels` is empty.
That is acceptable for manual review but too permissive for unattended paper execution.
Autonomy should fail closed for new risk and fail open only for risk-reducing exits.

### Exit Criteria

Auto-mode new BUYs cannot route without the evidence/scan artifacts when the config requires them.
SELL exits remain routable without those artifacts.
The gate summary distinguishes `skipped` from `blocked`.

### Verification

Add tests for missing snapshot with BUY blocked.
Add tests for missing snapshot with SELL still allowed.
Run `python -m pytest tradeloop/tests/test_cycle_guards.py tradeloop/tests/test_router_gate.py`.

## Phase 4: Align Scheduler And Operator Docs With Autonomy

### Files

`tradeloop/scripts/cron_dispatch.sh`
`tradeloop/scripts/crontab.txt`
`README.md`
`tradeloop/README.md` if present and stale
`tradeloop/docs/operator-runbook.md` if present and stale

### Changes

Update premarket comments from `propose-only` to `autonomous paper route after gates pass`.
Update intraday comments to explain it manages holdings and may auto-route exits or approved top-ups for existing positions only.
Update postclose comments to say it never fills orders but may write stop updates/carry-forward context.
Resolve README merge conflict markers completely.
Document paper-first automation as the default.
Document live auto as disabled by default and requiring an explicit config change.
Document dashboard as the primary supervision surface.

### Exit Criteria

No `<<<<<<<`, `=======`, or `>>>>>>>` markers remain in README files.
Docs no longer claim every cycle stops at `AWAITING_APPROVAL`.
Docs accurately describe `approval_mode: auto` and `allow_auto_live: false`.

### Verification

Run `python -m pytest tradeloop/tests/test_model_routing_doc.py tradeloop/tests/test_schedule_health.py`.
Run `rg '<<<<<<<|=======|>>>>>>>' README.md tradeloop docs` and confirm no merge markers remain.

## Phase 5: Redesign Dashboard Information Architecture

### Files

`tradeloop/dashboard/static/index.html`
`tradeloop/dashboard/server.py`
`tradeloop/dashboard/status.py`
`tradeloop/dashboard/runs.py`
`tradeloop/tests/dashboard/test_status.py`
`tradeloop/tests/dashboard/test_runs.py`
`tradeloop/tests/dashboard/test_server.py`

### Target Layout

The dashboard should become a dynamic website with top navigation.

Tabs:

1. `Overview`
2. `Autopilot`
3. `Portfolio`
4. `Latest Decision`
5. `Risk And Gates`
6. `Agents`
7. `History`

The default view should be `Overview`, not the historical run picker.
The run picker should move into `History`.
The selected run should default to latest run but not dominate the page.

### Visual Direction

Use a dark trading-console base with high-contrast glass panels.
Use color sparingly for state: green for passed/filled, amber for warning/pending, red for blocked/risk, blue for automation/info.
Use large current-state hero cards at the top.
Use compact dense tables below.
Use responsive CSS grid, not fixed `max-width: 780px`.
Use tabular numerals for INR, P&L, token, quantity, and percentage fields.
Avoid emoji.
Avoid generic pastel cards.

### CSS Implementation Details

Keep all CSS in `index.html` for this batch.
Define variables:

```css
:root {
  --bg: #070a12;
  --panel: #101725;
  --panel-soft: #151f31;
  --line: rgba(148, 163, 184, 0.18);
  --text: #eef3ff;
  --muted: #8fa1bd;
  --green: #38d996;
  --amber: #f5bd4f;
  --red: #ff6b6b;
  --blue: #70a7ff;
}
```

Use layout containers:

```css
.app-shell
.topbar
.hero-grid
.panel
.panel-header
.metric-grid
.data-table
.gate-timeline
.agent-timeline
.tabbar
.tab-panel
```

Use mobile breakpoint at `760px`.
On mobile, topbar wraps, hero grid becomes one column, tables become horizontally scrollable.

### JavaScript Implementation Details

Replace current render flow with a small client-side state object:

```js
const state = {
  activeTab: 'overview',
  currentRun: null,
  runs: [],
  status: null,
  portfolio: null,
  run: null,
  refreshTimer: null,
};
```

Add functions:

```js
async function refreshAll()
async function loadRuns()
async function loadStatus()
async function loadPortfolio()
async function loadRun(dir)
function renderApp()
function renderOverview()
function renderAutopilot()
function renderPortfolio()
function renderLatestDecision()
function renderRiskAndGates()
function renderAgents()
function renderHistory()
function switchTab(tab)
function statusPill(label, status)
function gateRow(gate)
```

Poll every 5 seconds only when the latest run is live or when a run has just been started.
Use manual refresh button for normal state.
Disable `Route paper orders` on the main dashboard unless the selected run has proposed orders and is not already routed.
Because paper auto-routing is the default, manual route should be shown as an exception action in History, not a primary hero button.

### Exit Criteria

Landing page immediately answers: is autopilot on, did the last cycle trade, why, and what risk is open.
History is available but not the primary interface.
The dashboard works on desktop and mobile.
No frontend dependency is added.

## Phase 6: Add Dashboard API Transparency Payloads

### Files

`tradeloop/dashboard/status.py`
`tradeloop/dashboard/runs.py`
`tradeloop/dashboard/server.py`
`tradeloop/tests/dashboard/test_status.py`
`tradeloop/tests/dashboard/test_runs.py`

### Extend `/api/status`

Add:

```json
{
  "autonomy": {
    "approval_mode": "auto",
    "paper_auto_route": true,
    "allow_auto_live": false,
    "live_trading_env_enabled": false,
    "effective_mode": "paper_autonomous"
  },
  "next_scheduled_cycles": [],
  "operator_attention": []
}
```

`effective_mode` should be one of:

`paper_autonomous`, `paper_human_loop`, `live_locked`, `live_auto_enabled`, `halted`.

`operator_attention` should include concise objects such as:

```json
{"severity": "critical", "title": "Kill switch active", "detail": "No routes will execute."}
```

### Extend `/api/run`

Add:

```json
{
  "orders": [],
  "fills": [],
  "gates": [],
  "manager_backchannel": null,
  "run_status": "routed",
  "route_summary": {
    "filled": 1,
    "risk_rejected": 0,
    "mode_blocked": 0,
    "stops_tightened": 0
  }
}
```

Normalize old run artifacts gracefully.
If `gate_summary.json` is missing, synthesize best-effort gate rows from existing files.
Do not break existing `stages`, `decision`, or `usage` fields.

### Run Status Rules

Use `reasoning_error.txt` as `failed`.
Use missing dict-shaped `orders.json` as `running`.
Use `fills_summary.md` with `result: BLOCKED` as `blocked`.
Use non-empty `fills.json` as `routed`.
Use proposed orders and no fills as `awaiting_exception_review` in paper auto mode.
Use proposed orders and no fills as `awaiting_approval` only in human-in-loop mode.

### Exit Criteria

The frontend never parses markdown/prose directly.
The frontend has all fields needed to render transparent state.
Old runs still render.

### Verification

Run `python -m pytest tradeloop/tests/dashboard/test_status.py tradeloop/tests/dashboard/test_runs.py tradeloop/tests/dashboard/test_server.py`.

## Phase 7: Build Overview Tab

### Files

`tradeloop/dashboard/static/index.html`

### Content

Top hero should show:

`Autopilot: Paper Auto` or `Autopilot: Halted`.
`Last Cycle: Routed / Blocked / Running / Holding`.
`Open Risk: deployed %, open positions, stop risk if available`.
`Data: Fresh / Stale / Missing`.

Below hero:

`Last Decision` panel with primary sentence and order chips.
`Needs Attention` panel sourced from `/api/status.operator_attention`.
`Portfolio Snapshot` panel with equity, cash, invested, realized, unrealized.
`Gate Outcome` mini timeline from latest run.

### Exit Criteria

User can understand bot state without touching the history dropdown.
Critical blockers are visible above the fold.

## Phase 8: Build Autopilot Tab

### Files

`tradeloop/dashboard/static/index.html`

### Content

Show effective automation state:

Paper auto-route enabled or disabled.
Live env enabled or disabled.
Live auto allowed or locked.
Kill switch status.
Promotion readiness and reasons.
Source freshness.
Latest schedule health if available from reports.

Controls:

`Run premarket now` button should remain.
`Refresh dashboard` button.
`Route selected paper run` should move to an exception section and require confirm.
Do not add live-send buttons in this batch.

### Exit Criteria

The tab makes it impossible to confuse paper autonomy with live autonomy.
The user sees exactly why live is locked.

## Phase 9: Build Latest Decision Tab

### Files

`tradeloop/dashboard/static/index.html`
`tradeloop/dashboard/runs.py`

### Content

Render normalized `orders` and `fills` as a table.
Columns:

`Stock`, `Side`, `Qty`, `Price`, `Stop`, `Target 1`, `Strategy`, `Conviction`, `Route Status`, `Reason`.

Add a decision narrative card:

`What the bot decided`.
`Why it decided this` from PM decision/order reasons.
`What could go wrong` from risk report or bear/debate summaries.
`What happened after routing` from fills.

### Exit Criteria

A non-technical user can tell whether a trade was proposed, filled, rejected, or blocked and why.

## Phase 10: Build Risk And Gates Tab

### Files

`tradeloop/dashboard/static/index.html`
`tradeloop/dashboard/portfolio.py`
`tradeloop/dashboard/runs.py`

### Content

Gate timeline with statuses and details.
Risk cap cards:

`max position allocation`, `max total deployed`, `max sector exposure`, `max open positions`, `daily drawdown circuit`, `min position size`.

Current exposure table:

`Position`, `Market Value`, `% Equity`, `Stop`, `Distance To Stop`, `Unrealized P&L`.

If sector exposure is available, render sector exposure bars.
If sector exposure is not available, show `Sector exposure unavailable` instead of inventing it.

### Backend Details

Extend `portfolio_view` with `exposure`:

```json
{
  "deployed_pct": 42.1,
  "open_positions": 3,
  "positions_limit": 4,
  "sector_exposure": []
}
```

Load settings and ticker master either in `server.py` before calling `portfolio_view` or in a new helper.
Keep existing portfolio fields for compatibility.

### Exit Criteria

Risk transparency is explicit, not hidden in agent prose.

## Phase 11: Build Agents Tab

### Files

`tradeloop/dashboard/static/index.html`
`tradeloop/dashboard/render.py`
`tradeloop/dashboard/runs.py`

### Content

Render the current run stages as a vertical timeline.
Each stage should show:

Stage name.
Plain-English role.
Model used.
Status: done/running/missing/failed.
Summary.
Expandable bullet details.
Token/cost row from `usage.by_stage`.

### Backend Details

Add `status` to stage cards when artifacts are missing or errors exist.
For current behavior, default existing rendered stages to `done`.
Add synthetic missing stages only if useful for latest live run; do not pollute old completed run views.

### Exit Criteria

The dashboard explains the multi-agent chain without requiring file browsing.

## Phase 12: Build History Tab

### Files

`tradeloop/dashboard/static/index.html`
`tradeloop/dashboard/runs.py`

### Content

Move the run selector/list here.
Render history as a searchable table or card list.
Columns:

`Time`, `Mode`, `Outcome`, `Orders`, `Filled`, `Blocked`, `Cost`, `Tokens`.

Clicking a row sets `state.currentRun` and updates Latest Decision, Risk And Gates, and Agents tabs.
Keep URL hash support if simple: `#run=2026...&tab=history`.

### Exit Criteria

History exists but does not dominate the main dashboard.

## Phase 13: Browser QA And Pixel Pass

### Files

No planned source files unless issues are found.

### Steps

Run `python -m tradeloop.dashboard`.
Open `http://127.0.0.1:8765`.
Check desktop at `1440x1000`.
Check tablet/mobile at `390x844`.
Verify no horizontal page overflow except inside tables.
Verify color contrast for text on panels.
Verify empty states look intentional.
Verify live-price-unavailable state is clear.
Verify latest run polling does not spam the server.

### Exit Criteria

Dashboard is usable and polished on desktop and mobile.
Primary state is understandable within five seconds.

## Phase 14: Final Test Matrix

### Commands

Run targeted tests first:

```bash
python -m pytest tradeloop/tests/test_config.py tradeloop/tests/test_approval.py tradeloop/tests/test_e2e_auto_route.py
python -m pytest tradeloop/tests/dashboard
python -m pytest tradeloop/tests/test_router_gate.py tradeloop/tests/test_cycle_guards.py
```

Run broader suite if targeted tests pass:

```bash
python -m pytest tradeloop/tests
```

Run health verification:

```bash
python tradeloop/scripts/verify_setup.py --health
```

Do not run commands that print `.env` or secret-like environment variables.

## Suggested Branch Breakdown

### PR 1: Paper-First Automation Contract

Phases: 1, 2, 3, 4.
Purpose: align config, gates, artifacts, and docs with autonomous paper trading.
Risk: changes route behavior for auto BUYs when data artifacts are missing.
Rollback: revert config and gate-summary/autonomy guard changes.

### PR 2: Dashboard API Transparency

Phases: 5, 6, 10 backend pieces, 11 backend pieces, 12 backend pieces.
Purpose: expose stable structured data for the modern dashboard.
Risk: old runs may have sparse artifacts.
Rollback: keep old fields unchanged and only remove new fields if needed.

### PR 3: Modern Dynamic Dashboard UI

Phases: 7, 8, 9, 10 frontend, 11 frontend, 12 frontend, 13.
Purpose: ship the new website-style cockpit.
Risk: static HTML grows large.
Rollback: restore previous `index.html` while keeping backend transparency payloads.

## Hard Safety Invariants

Never auto-place live Zerodha orders in this batch.
Never let LLM output bypass deterministic sizing.
Never let LLM output bypass `evaluate()` risk gates.
Never route when kill switch is active.
Never route live when `allow_auto_live` is false.
Never use missing evidence or missing scan grounding as a silent pass for autonomous new BUYs.
Never block risk-reducing SELL exits only because news or scan data is stale.
Never hide route rejection reasons behind generic UI copy.

## Definition Of Done

Paper cycles can run and route automatically after gates pass.
Live auto-routing is visibly locked by default.
Every route/block has a structured gate summary.
The dashboard opens to a dynamic Overview rather than a run picker.
The dashboard has a separate History tab.
The UI clearly shows autopilot state, latest decision, gate reasons, portfolio, risk, and agent reasoning.
All targeted tests pass.
Browser QA passes on desktop and mobile.
