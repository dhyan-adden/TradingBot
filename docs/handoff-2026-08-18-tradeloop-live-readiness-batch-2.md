# TradeLoop Handoff - 2026-08-18 (live readiness batch 2)

Resume point for a fresh worker session.
This file extends `docs/handoff-2026-08-18-tradeloop-live-readiness-hardening.md`.
Batch 1 completed the live gates and left live routing safe but intentionally blocked because no broker snapshot producer exists yet.

## One-line state

TradeLoop can propose and paper-route safely.
Live routing is still blocked by design because `live_reconcile.json` is required but no running step writes it.
This batch wires in the missing read-only broker-state producer and closes the `auto` policy gap without adding direct Python order execution.

## Objective

Make live routing mechanically ready for a one-share canary while preserving payload-first execution.

The target route flow is:

`orders.json -> approval/auto policy gate -> read-only Zerodha snapshot -> Python reconciliation -> live_reconcile.json -> deterministic risk gate -> live MCP payload`

The actual broker order call remains separate and still requires the Zerodha MCP `confirm=true` guard.

## Non-negotiable constraints

- Do not inspect, print, grep, parse, or summarize `.env` or any secret value.
- Do not print values for names containing `KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `AUTH`, or `CREDENTIAL`.
- Python must not own Zerodha credentials.
- A TypeScript script may consume credentials internally the same way `src/mcp/zerodha.ts` and `scripts/zerodha-auth.ts` do, but it must never print them.
- Keep `human_in_loop` as the default approval mode.
- `approval_mode: auto` must not live-route unless `allow_auto_live: true` is set.
- Do not compare live broker positions against the paper ledger as the source of truth for live holdings.
- Keep paper ledger for promotion/performance only.
- Add a separate live expected-position book for live routing.
- Do not build a direct Python Zerodha order executor.
- Keep live order generation payload-first: `READY_FOR_CODEX_TOOL_CALL` is still the terminal Python live action.
- The first live phase remains one-share BUY canary only.

## Current code seams

| File | Current role |
| --- | --- |
| `tradeloop/orchestrator.py` | `route_cycle()` checks promotion, human approval, and `live_reconcile_allows_route()` before routing. |
| `tradeloop/lib/broker/live_state.py` | Has `LiveBrokerSnapshot`, `compute_reconciliation()`, `persist_reconciliation()`, and the live route gate. |
| `tradeloop/lib/broker/router.py` | Builds live MCP payloads and enforces canary BUY quantity. |
| `tradeloop/lib/approval.py` | Validates `approval.json` for `human_in_loop`. |
| `tradeloop/lib/config.py` | Loads `approval_mode` and `allow_auto_live`, but `allow_auto_live` is not enforced yet. |
| `src/mcp/zerodha.ts` | Already has read-only MCP tools for holdings, positions, orders, and margins, plus guarded place-order. |
| `package.json` | Already has `tsx`, `typescript`, and `npm run typecheck`. |

Confirmed gaps before this batch:

- `persist_reconciliation()` and `persist_snapshot()` are defined and tested but no production code calls them.
- `allow_auto_live` is loaded and tested in config but no production route path consults it.

## Design decisions

### Keep Python out of secrets

The broker-state fetch must live in TypeScript, near the existing Zerodha MCP credential path.
The TypeScript side may call Kite read-only endpoints and write a sanitized JSON snapshot.
The Python side only reads the sanitized snapshot, computes deterministic reconciliation, and blocks or allows payload generation.

### Add a live expected-position book

Do not use the paper book as live ownership truth.
The paper ledger contains simulated positions and must not authorize real SELL orders.

Add `tradeloop/state/live_book.json` as a non-secret local state file.
It should contain only symbols and quantities that TradeLoop believes it owns live.

Suggested shape:

```json
{
  "updated_at": "2026-08-18T00:00:00+00:00",
  "positions": {
    "RELIANCE": 1
  },
  "source": "zerodha_order_sync"
}
```

Missing `state/live_book.json` means an empty expected live book.
That allows first canary BUY but blocks SELL of symbols TradeLoop did not previously record as live-owned.

### Reconciliation is pre-route, not post-fact justification

`route_cycle()` must refresh broker state immediately before the existing `live_reconcile_allows_route()` check.
A stale `live_reconcile.json` must not be accepted unless it was just refreshed and is within `MAX_AGE_SECONDS`.

## Implementation phases

### Phase 1 - Enforce `auto` live policy

Goal: close the `allow_auto_live` gap before building any live broker plumbing.

Files:

- `tradeloop/orchestrator.py`
- `tradeloop/tests/test_approval.py` or a new `tradeloop/tests/test_auto_live_policy.py`

Implementation:

- Add a small helper, either in `tradeloop/lib/approval.py` or inline in `route_cycle()`, that treats auto live as disabled unless `settings.allow_auto_live` is true.
- In `route_cycle()`, after `LIVE_NOT_READY` and before human approval/reconciliation, add:

```python
if live_enabled() and settings.approval_mode == "auto" and not settings.allow_auto_live:
    print("tradeloop_route=AUTO_LIVE_DISABLED")
    return 2
```

Rules:

- `human_in_loop` behavior must not change.
- `auto` still requires promotion, kill-switch pass, broker reconciliation, risk gate, and canary cap.
- `auto` must not require `approval.json`.

Tests:

- Live + `approval_mode=auto` + `allow_auto_live=False` returns `2` and prints `AUTO_LIVE_DISABLED`.
- Live + `approval_mode=auto` + `allow_auto_live=True` proceeds to the reconciliation gate.
- Live + `human_in_loop` still requires `approval.json`.
- Paper route ignores `allow_auto_live` entirely.

### Phase 2 - Add live expected-position book

Goal: prevent TradeLoop from selling broker holdings it did not open/manage live.

Files:

- `tradeloop/lib/broker/live_book.py` (new)
- `tradeloop/lib/broker/live_state.py`
- `tradeloop/tests/test_live_book.py` (new)
- `tradeloop/tests/test_live_reconciliation.py`

Implementation:

- Add `load_live_expected_book(root: Path) -> dict[str, int]`.
- Read `root / "state" / "live_book.json"`.
- If missing, return `{}`.
- If malformed, fail closed by returning an error status or raising a narrow exception that route code converts into a blocked reconciliation.
- Normalize symbols to uppercase and quantities to non-negative integers.
- Add `persist_live_expected_book(root: Path, positions: dict[str, int], source: str) -> None` for post-execution sync in a later phase.

Update `compute_reconciliation()` so SELLs must satisfy both conditions:

- `sell_quantity <= snapshot.holdings.get(symbol, 0)`.
- `sell_quantity <= expected_book.get(symbol, 0)`.

Reason:
broker holdings alone prove the account owns shares, but not that TradeLoop is authorized to manage them.

Tests:

- Missing `live_book.json` loads `{}`.
- Malformed `live_book.json` fails closed.
- SELL is blocked when broker holds shares but expected live book has zero.
- SELL is allowed only when both broker-held and expected-live quantities are sufficient.
- BUY remains allowed with an empty expected live book if cash and duplicate-order checks pass.

### Phase 3 - Add read-only Zerodha snapshot writer

Goal: create the production producer for `live_broker_snapshot.json` without Python touching credentials.

Files:

- `scripts/zerodha-live-snapshot.ts` (new)
- `package.json`
- `tsconfig.json` if needed only for typecheck compatibility.

Implementation:

- Add an npm script:

```json
"live:snapshot": "tsx scripts/zerodha-live-snapshot.ts"
```

- The script accepts `--run-dir <path>`.
- It uses the same credential style as `src/mcp/zerodha.ts`: internal environment consumption only, no printing secret values.
- It calls read-only Kite endpoints:
  - `/portfolio/holdings`
  - `/portfolio/positions`
  - `/orders`
  - `/user/margins/equity`
- It writes `<run_dir>/live_broker_snapshot.json` in the exact `LiveBrokerSnapshot` shape:

```json
{
  "checked_at": "2026-08-18T00:00:00.000Z",
  "auth_ok": true,
  "holdings": {
    "RELIANCE": 1
  },
  "open_orders": [
    {"symbol": "RELIANCE", "side": "BUY", "quantity": 1, "status": "OPEN"}
  ],
  "available_cash_inr": 100000.0
}
```

Normalization rules:

- Include only NSE equity symbols relevant to cash-equity routing.
- Merge long-term holdings and positive net/day positions conservatively.
- Ignore negative quantities for holdings map; shorts are outside TradeLoop's mandate and should instead create a blocked status if seen for a proposed symbol.
- Only include open/pending orders in `open_orders`; completed/cancelled/rejected orders should not conflict.
- Available cash should use the most conservative equity cash field available from Kite margins.
- If a field is missing or ambiguous, fail closed by exiting non-zero or writing `auth_ok: false` plus empty state.

Security rules:

- Do not print raw Kite responses to stdout/stderr.
- Do not print credentials or environment values.
- On auth failure, print only a status line such as `zerodha_live_snapshot=AUTH_FAILED` and exit non-zero.
- The snapshot file must contain positions, open orders, cash, and timestamps only.

Tests and verification:

- `npm run typecheck` passes.
- Add a small pure TypeScript normalizer function if practical and unit-test it only if the repo has or adds a lightweight TS test command.
- If no TS test harness exists, keep the normalizer small and cover behavior through Python integration tests using fixture snapshots.

### Phase 4 - Add Python refresh function and wire route cycle

Goal: make `route_cycle()` generate fresh reconciliation before checking `live_reconcile_allows_route()`.

Files:

- `tradeloop/lib/broker/live_state.py`
- `tradeloop/orchestrator.py`
- `tradeloop/tests/test_live_reconciliation.py`

Implementation:

- Add `load_snapshot(run_dir: Path) -> LiveBrokerSnapshot | None`.
- Add `refresh_live_reconciliation(run_dir: Path, root: Path, orders_path: Path) -> LiveReconciliationStatus`.
- `refresh_live_reconciliation()` should:
  - Run `npm run --silent live:snapshot -- --run-dir <run_dir>` with a short timeout.
  - Never pass secrets on the command line.
  - Never print captured output unless it is a known safe status line.
  - Load `live_broker_snapshot.json`.
  - Load `orders.json` via `load_orders()` and convert orders to tickets or pass typed orders into `compute_reconciliation()`.
  - Load expected live book via `load_live_expected_book(root)`.
  - Call `compute_reconciliation(snapshot, orders, expected_book)`.
  - Persist `live_reconcile.json`.
  - Return the status.
- In `route_cycle()`, replace the current pre-route check:

```python
if live_enabled() and not live_reconcile_allows_route(run_dir):
    print("tradeloop_route=LIVE_RECONCILE_BLOCKED")
    return 2
```

with:

```python
if live_enabled():
    refresh_live_reconciliation(run_dir, root, orders_path)
    if not live_reconcile_allows_route(run_dir):
        print("tradeloop_route=LIVE_RECONCILE_BLOCKED")
        return 2
```

Rules:

- Refresh must happen after approval/auto policy and before payload generation.
- Paper routes must not call the snapshot writer.
- If snapshot command fails, persist a not-ok reconciliation if possible and block.
- If the snapshot file is malformed or missing after the command, block.

Tests:

- Live route calls `refresh_live_reconciliation()` before `route_orders_file()`.
- Live route blocks when refresh writes not-ok reconciliation.
- Live route proceeds to `route_orders_file()` when refresh writes fresh ok reconciliation.
- Paper route does not call refresh.
- Snapshot command failure blocks and does not create `fills.json`.
- Malformed snapshot blocks.

### Phase 5 - Add post-live order sync plan hooks, not auto mutation

Goal: avoid pretending a payload equals a broker fill.

Files:

- `docs/handoff-2026-08-18-tradeloop-live-readiness-batch-2.md`
- Optional later file: `scripts/zerodha-live-sync.ts`
- Optional later file: `tradeloop/lib/broker/live_book.py`

Implementation for this batch:

- Do not update `live_book.json` when Python merely emits `READY_FOR_CODEX_TOOL_CALL`.
- Add comments/docs that live book updates happen only after a confirmed broker fill/trade sync.
- If a worker implements sync in the same batch, it must be read-only and use `zerodha_orders`/`zerodha_order_trades` or equivalent Kite endpoints to confirm actual fills.

Reason:
Python payload generation is not execution.
Updating live expected positions before a real fill would create false ownership and could later authorize a SELL.

Success criteria:

- Live BUY payload generation does not mutate `state/live_book.json`.
- A future fill-sync tool has a clear place to update live book only after broker-confirmed fills.

### Phase 6 - Refresh stale docs and operational runbook

Goal: avoid operators following old live-readiness rules.

Files:

- `docs/tradeloop-overview.html`
- Any live-readiness section in current project docs that still says markdown `live_ready: true` unlocks live.

Implementation:

- Update user-facing docs to say live requires:
  - 60 closed paper trades.
  - Clean audits.
  - Approval or `auto` with `allow_auto_live: true`.
  - Fresh read-only Zerodha reconciliation.
  - One-share canary cap.
  - Separate MCP confirmation.
- Do not rewrite historical handoff files unless they are operator-facing for current execution.

## Acceptance checklist

- `allow_auto_live` is enforced in `route_cycle()`.
- `approval_mode: auto` with `allow_auto_live: false` returns `AUTO_LIVE_DISABLED` before broker snapshot refresh.
- Live route invokes read-only snapshot refresh before reading `live_reconcile.json`.
- Paper route never invokes snapshot refresh.
- Missing/malformed/stale broker snapshot blocks live.
- Missing `state/live_book.json` defaults to empty expected live positions.
- SELL is blocked unless both broker-held and expected-live quantities are sufficient.
- BUY canary remains capped at one share.
- Python never places a live Zerodha order.
- TypeScript snapshot writer never prints secrets.
- `pytest tradeloop/tests -q -W error` passes.
- `npm run typecheck` passes.

## Verification commands

Run from repo root:

```bash
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q -W error
npm run typecheck
```

Do not run commands that print environment variables.
Do not inspect `.env`.

## Worker instructions

- Start with Phase 1.
- Do not build the TypeScript snapshot writer until the auto gate test is red, fixed, and green.
- Keep changes surgical and aligned to the files listed in each phase.
- Add tests before wiring route behavior.
- Treat auth failures as expected runtime states that block live safely.
- Do not log raw Kite API responses.
- Do not mutate live expected positions when only a payload was generated.
- If live snapshot normalization is ambiguous, fail closed and document the exact field that was ambiguous.

## Definition of done

This batch is done when:

- The missing producer for `live_broker_snapshot.json` exists.
- `route_cycle()` refreshes and persists `live_reconcile.json` before live payload generation.
- `allow_auto_live` is enforced.
- Live SELLs cannot be authorized by paper positions or manually-held broker shares alone.
- Payload-first execution is preserved.
- Full pytest and TypeScript typecheck pass.

## Implementation status

Implemented and verified.

- Phase 1: `route_cycle()` now returns `AUTO_LIVE_DISABLED` when `approval_mode=auto` and `allow_auto_live=false`. Tests in `test_approval.py`.
- Phase 2: `tradeloop/lib/broker/live_book.py` (`load_live_expected_book`, `persist_live_expected_book`); `compute_reconciliation()` enforces the dual SELL bound (broker-held AND live-book). Tests in `test_live_book.py`.
- Phase 3: `scripts/zerodha-live-snapshot.ts` + `npm run live:snapshot`; read-only Kite fetch, sanitized snapshot, status-line-only output, fail closed on auth/fetch/cash-missing. Verified `npm run typecheck`.
- Phase 4: `refresh_live_reconciliation()` in `live_state.py` runs the snapshot producer, recomputes, persists; `route_cycle()` calls it before `live_reconcile_allows_route()`. Tests in `test_live_reconciliation.py`.
- Phase 5: payload generation never mutates `state/live_book.json`; note added in `router.py`; fill-sync hook reserved in `live_book.py`.
- Phase 6: `docs/tradeloop-overview.html` safety flags updated to the current gate set.

Verification: `pytest tradeloop/tests -q -W error` -> 431 passed, 1 skipped. `npm run typecheck` -> clean.
