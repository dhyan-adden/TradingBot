# TradeLoop: Claude-subscription reasoning backend

Date: 2026-07-10
Status: Approved design, ready for implementation plan
Owner: dhyan-hokage

## Problem

The default reasoning backend routes the 13-stage DAG through OpenRouter models (minimax, mimo, deepseek-flash).
OpenRouter output is inconsistent: empty content, hollow `{}`, truncation, and reasoning-token overruns, each of which the client carries scar tissue to survive.

A second backend exists (`--backend claude`) that is supposed to run the work on the Claude subscription via 13 named subagents.
It does not actually do that.
The live run `2026-07-09_1129_premarket` was dispatched through the claude entrypoint yet produced OpenRouter provenance for all 11 stages: the `claude -p` master session drove the OpenRouter Python DAG instead of dispatching subagents.
Relying on an LLM master session to fan out to 13 subagents in order, and never touch OpenRouter, is non-deterministic and empirically failed.

## Goal

Run every reasoning call on the Claude subscription, with per-stage model tiers, while keeping the deterministic Python driver that already owns stage order, sizing, gates, provenance, and `orders.json`.

Tiering (unchanged from the existing agent definitions):

- haiku: `11_sentiment`, `05_adhoc_intake`
- sonnet: `10_news`, `12_fundamentals`, `13_technical`, `14_shortlist`, `20_bull`, `21_bear`, `50_post_trade`
- opus: `22_debate`, `30_trade_plan`, `40_risk_report`, `41_pm_decision`

Second goal, enabled by the same change: feed the full tradeable scan to the screening analysts instead of a pre-truncated top 150.
Real scans are 236 to 448 setups, so the current `max_setups_downstream: 150` ceiling silently drops roughly half of them before any reasoning sees them.
The full setup block is about 20 to 25k tokens, trivial inside Claude's context, so the cap is a small-model artifact the Claude backend removes.
Semantics stay the funnel as designed: every setup is screened by the technical and shortlist stages, and the top roughly 12 still receive the deep bull, bear, debate, and trade treatment.

## Non-goals

Metered Anthropic API usage is out of scope; the subscription is reached only through the local `claude -p` CLI.
No cloud routine, no n8n, no VPS in this change; deployment stays the local cron on the Mac (VPS is a later, code-identical migration, noted at the end).
The intraday and postclose live paths remain unscheduled; this change is validated on `premarket`.

## Approach

Keep the deterministic driver, swap only the per-stage transport.

The trustworthy loop in `_run_reasoning_openrouter` already wraps sizing, the evidence and grounding gates, provenance, and Python-owned `orders.json`.
Extract that loop into one client-agnostic function and call it from both backends with a different client object.
The OpenRouter path keeps `LLMClient`; the claude path gets a new `ClaudeStageClient` that invokes `claude -p` once per stage.
Nothing about the DAG, sizing, or gates changes.

```text
backend=openrouter  ->  LLMClient          (httpx -> OpenRouter, unchanged, dormant fallback)
backend=claude      ->  ClaudeStageClient  (subprocess -> claude -p, new)
                              \____ both feed the SAME _run_reasoning_dag loop ____/
```

### Rejected alternatives

Fix the master-session subagent dispatch (Approach 2): rejected, it is the exact pattern that just failed, and it discards the Python-owned determinism.
Anthropic Messages API (Approach 3): rejected, clean structured output but metered dollars, not the subscription.

## Components

### 1. `_run_reasoning_dag(run_dir, mode, timeout, client, settings)` (orchestrator.py)

Extract the current body of `_run_reasoning_openrouter` verbatim into this function, parameterized by an injected `client` that satisfies the existing `SupportsCallJson` protocol.
`_run_reasoning` dispatches on backend: it constructs `LLMClient` for `openrouter` and `ClaudeStageClient` for `claude`, then calls `_run_reasoning_dag` for both.
The `generated_by` field in `orders.json` is set from the backend (`tradeloop.reasoning.claude` or `tradeloop.reasoning.p1`) so provenance stays truthful.

Deleted as part of this change: `_run_reasoning_claude` (the shell master-session path) and `_canonicalize_claude_orders`.
The `claude)` branch in `scripts/run_cycle.sh` becomes dead; it is flagged and removed since nothing else invokes it.

### 2. `ClaudeStageClient` (new: lib/llm/claude_client.py)

Implements `call_json(role, system, user, schema, model=None) -> BaseModel`, matching `SupportsCallJson`.

Per call it runs, via `subprocess.run` with a timeout:

```text
claude -p "<system + schema_hint + user>" --model <tier> --output-format json --max-turns 1
```

`--max-turns 1` forces a single-shot generation with no agentic loop; no MCP is wired on this path (stages read the frozen artifacts passed in the prompt, exactly as the OpenRouter stages do, so price grounding stays deterministic in Python).

Output handling reuses the existing helpers from `lib/llm/client.py`:

- Parse the `--output-format json` envelope; take `result` as the model text.
- Reuse `_first_json_object` + `json.loads` + `schema.model_validate` (the same brace-balanced extraction and pydantic validation the OpenRouter client uses).
- Reject a hollow `{}` with the same rule already in `_parse_json_object`.
- On parse or validation failure, retry up to `max_retries` on the same tier; no cross-model fallback is needed.
- On repeated failure raise `LLMValidationError` (reuse the existing exception).

Provenance parity: write a `CallRecord` to the same `llm_calls.jsonl` audit path.
`model` records `claude:<tier>`, `response_id` uses the envelope `session_id`, token counts come from the envelope `usage` when present.
The dashboard, reconcile, and attribution code read this file unchanged.

### 3. `CLAUDE_STAGE_MODELS` + `claude_model_for(stage)` (lib/llm/routing.py)

Add a table next to the existing `STAGE_MODELS`, mapping each stage to `"haiku" | "sonnet" | "opus"` per the tiering above.
`routing.py` becomes the single source of truth for the claude tiers.
The `.claude/agents/tradeloop-*.md` model frontmatter is now vestigial for this path; it is left in place (harmless) and noted.

### 4. Cron flip (scripts/cron_dispatch.sh)

The 08:00 IST line changes from `orchestrator premarket` to `orchestrator premarket --backend claude`.
It stays local; the ledger and Kite MCP are local.
The in-code default backend stays `openrouter`, so unrelated callers and tests are unaffected and rollback is a one-flag change.

### 5. Timeout

`cycle_timeout_seconds` is already 1200 (20 minutes), which covers roughly 13 sequential `claude -p` calls.
No config change is planned; the first real E2E run confirms the margin, and only then is it adjusted if needed.

### 6. Lift the setup cap (config/settings.yaml + lib/data/ingest.py)

Set `universe.max_setups_downstream` to `null`, meaning analyze the full tradeable scan (no pre-truncation), and update its comment.
In `ingest.py`, `top_n` resolves to `None` when the config value is null, so the truncation line becomes conditional: `if top_n: setups = setups[:top_n]`.
A number still caps as before, so the knob remains for a pathological day and for the OpenRouter fallback.
The universe is already bounded by `max_symbols: 2500`, so an uncapped scan can never exceed that, and even 2500 setups render to roughly 75k tokens, well inside context.
`full_scan.jsonl` is unchanged; only the slice written to `02_setups_raw.md` grows.
The two stages that read `02_setups_raw.md` are `13_technical` and `30_trade_plan`, so the extra tokens land on exactly two Claude calls per cycle.

## Error handling

A stage that cannot produce valid output after retries raises, and the existing DAG loop records `reasoning_error.txt` and fails the cycle with `REASONING_FAILED`, unchanged.
A partial run never masquerades as a clean hold.
`claude -p` process failures (nonzero exit, subprocess timeout) are caught inside `ClaudeStageClient` and surface as the same retry-then-raise path.

## Robustness requirements (the Python spine)

The reliability now rests on the deterministic driver, so the new transport is held to explicit guards.

Isolation by boundary: `ClaudeStageClient` implements the existing `SupportsCallJson` protocol and adds no orchestration logic; the proven DAG loop is reused verbatim and tested with a fake client, so the transport is fully swappable and independently unit-testable.

Per-call timeout: each `claude -p` subprocess gets its own timeout (about 120 seconds), so a single hung call cannot consume the whole cycle budget; the `cycle_timeout_seconds` deadline remains the outer bound.

Large-prompt safety: the prompt is written to the `claude -p` process on stdin, not passed as an argv, so the uncapped setup block from Change 2 can never hit `ARG_MAX`, and there is no shell interpolation of prompt content (argv list, never `shell=True`).

Preflight health: `scripts/verify_setup.py` gains a check that the `claude` CLI is authenticated before the cycle starts, so an expired login fails loudly at prepare, not mid-DAG at stage 7.

Fail loud, never silent: a stage that cannot produce schema-valid JSON after retries fails the cycle with `REASONING_FAILED`; it never writes an empty artifact that reads as a confident hold (the existing `{}`/empty rejection plus the DAG failure contract).

Subprocess hygiene: parse stdout only, capture stderr separately, and never log the prompt outside the provenance `CallRecord`.

Ultimate net: the propose/approve split means no stage output can reach the broker without passing the deterministic gates and your explicit approval, so even a bad stage cannot route a trade.

## Testing

Test plan follows the money-path standard: normal, edge, and failure branches, plus an E2E smoke as close to production as possible.

Unit (`tests/test_claude_client.py`, mock `subprocess.run`):

- Normal: a valid envelope with schema-conforming JSON returns the validated model and writes one `CallRecord`.
- Edge: prose-wrapped JSON is still extracted and validated.
- Failure: bad JSON then good JSON retries and succeeds; always-bad JSON raises `LLMValidationError`; hollow `{}` is rejected and triggers retry; nonzero exit and subprocess timeout retry then raise.

Regression: `test_cycle_guards.py`, `test_reasoning_wiring.py`, `test_llm_client.py`, `test_llm_routing.py`, `test_model_routing_doc.py` keep passing after the `_run_reasoning_dag` extraction.

Money-path: with a stub `ClaudeStageClient` returning a deliberately lowballed trade quantity, `orders.json` on the claude backend still shows the deterministic size (`_size_trade_plan` runs in the shared loop).
This proves the sizing gap identified in the current claude path is closed.

Setup cap (extend `tests/data/test_ingest_universe.py`): a scan larger than a numeric `max_setups_downstream` is still truncated to it (existing behaviour), and with the cap set to `null` every scanned setup reaches `02_setups_raw.md` with no truncation.

E2E smoke: run `orchestrator premarket --backend claude` against a prepared run directory with the real `claude -p`.
Assert `orders.json` is the Python dict shape, `llm_calls.jsonl` provenance shows only `claude:*` models and zero OpenRouter models, deterministic sizing was applied, and the evidence and grounding gates pass.

## Rollback

`--backend openrouter` continues to run the dormant `LLMClient` path.
Reverting production is a one-line change to `cron_dispatch.sh`.
If rolling back to OpenRouter, also restore a numeric `max_setups_downstream` (for example 150), since the small models cannot take the full uncapped setup block; the uncapped feed assumes the Claude backend.

## Deferred: VPS deployment

The whole design is host-agnostic; the same `orchestrator premarket --backend claude` runs on a persistent Linux VM later with no code change.
That migration adds three ops concerns, not code: authenticating the Claude CLI on the box (`claude setup-token`), automating the daily Zerodha access-token refresh, and a remote approval channel to trigger `orchestrator route <run_dir>`.
Out of scope here; captured for when local validation is done.

## Risks and open questions

Latency and subscription rate limits across 13 daily calls on the Max plan: expected fine for a once-daily propose, watched on the first runs.
`claude -p` JSON adherence: the schema hint plus `--max-turns 1` plus the existing brace extraction should keep output clean; the retry path covers stragglers.
A live probe on CLI 2.1.205 confirmed the envelope carries `result`, `session_id`, `usage`, and `modelUsage` (with the resolved model id and 200k context), and that `result` arrives fenced in a ```` ```json ```` block, which is why the brace-extraction helper is reused rather than a raw `json.loads`.
Per-call `claude -p` latency was about 4.6 seconds for a trivial call; real stage prompts run longer, but 13 sequential calls stay well inside the 1200 second cycle budget, and the per-call timeout bounds any single hang.
