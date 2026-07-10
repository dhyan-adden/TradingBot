#!/usr/bin/env bash
set -euo pipefail

CYCLE="${1:-premarket}"
RESUME_FROM=""
REQUEST_TEXT=""
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROMPT="$PROJECT_ROOT/tradeloop/prompts/00_master_orchestrator.md"
CARRY_FORWARD="$PROJECT_ROOT/tradeloop/memory/carry_forward_context.md"
# Prefer the project conda env (has all deps); fall back to PATH python3.
_DEFAULT_PY="/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python"
[[ -x "$_DEFAULT_PY" ]] || _DEFAULT_PY="python3"
TRADELOOP_PYTHON="${TRADELOOP_PYTHON:-$_DEFAULT_PY}"
# Master orchestrator model. Must be one of the four OpenRouter models.
TRADELOOP_MODEL="${TRADELOOP_MODEL:-minimax/minimax-m3}"
# Reasoning agent: codex (OpenRouter, the 4 models) or claude (native Claude subagents).
TRADELOOP_AGENT="${TRADELOOP_AGENT:-codex}"

case "$CYCLE" in
  premarket|intraday|postclose|adhoc) ;;
  *)
    echo "usage: $0 [premarket|intraday|postclose] [--resume-from stage]" >&2
    echo "       $0 adhoc \"user request\" [--resume-from stage]" >&2
    exit 2
    ;;
esac

shift || true
if [[ "$CYCLE" == "adhoc" ]]; then
  if [[ $# -eq 0 || "${1:-}" == "--resume-from" ]]; then
    echo "usage: $0 adhoc \"user request\" [--resume-from stage]" >&2
    exit 2
  fi
  REQUEST_TEXT="$1"
  shift || true
fi
if [[ "${1:-}" == "--resume-from" ]]; then
  RESUME_FROM="${2:-}"
fi

"$TRADELOOP_PYTHON" "$PROJECT_ROOT/tradeloop/scripts/verify_setup.py" --mode "$CYCLE"
if [[ -n "${TRADELOOP_RUN_DIR:-}" ]]; then
  RUN_DIR="$TRADELOOP_RUN_DIR"
elif [[ "$CYCLE" == "adhoc" ]]; then
  PREPARE_OUTPUT="$("$TRADELOOP_PYTHON" "$PROJECT_ROOT/tradeloop/scripts/prepare_cycle.py" --mode "$CYCLE" --request "$REQUEST_TEXT")"
  echo "$PREPARE_OUTPUT"
  RUN_DIR="${PREPARE_OUTPUT#tradeloop_run_dir=}"
else
  PREPARE_OUTPUT="$("$TRADELOOP_PYTHON" "$PROJECT_ROOT/tradeloop/scripts/prepare_cycle.py" --mode "$CYCLE")"
  echo "$PREPARE_OUTPUT"
  RUN_DIR="${PREPARE_OUTPUT#tradeloop_run_dir=}"
fi

# Make the OpenRouter key available to the Codex model provider. Reads only this
# one var, internally, and never prints it (same allowance as the Zerodha MCP).
if [[ -z "${OPENROUTER_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
  export OPENROUTER_API_KEY="$(grep '^OPENROUTER_API_KEY=' "$PROJECT_ROOT/.env" | head -1 | cut -d= -f2-)"
fi

INSTRUCTION="Run TradeLoop cycle: $CYCLE. Resume from: ${RESUME_FROM:-start}. Request: ${REQUEST_TEXT:-scheduled cycle}. Prepared run directory: $RUN_DIR. Carry-forward context file: $CARRY_FORWARD. Use this exact run directory only. Do not run prepare_cycle.py and do not create another run folder. Follow $PROMPT and write artifacts into $RUN_DIR."

case "$TRADELOOP_AGENT" in
  codex)
    exec "$PROJECT_ROOT/bin/codex-zerodha" --search -a never \
	      --model "$TRADELOOP_MODEL" \
	      -c 'model_provider="openrouter"' \
	      -c 'model_providers.openrouter.name="OpenRouter"' \
	      -c 'model_providers.openrouter.base_url="https://openrouter.ai/api/v1"' \
	      -c 'model_providers.openrouter.env_key="OPENROUTER_API_KEY"' \
	      -c 'model_providers.openrouter.wire_api="responses"' \
	      exec \
	      -s workspace-write \
	      -C "$PROJECT_ROOT" \
	      --skip-git-repo-check \
	      "$INSTRUCTION"
    ;;
  *)
    # The claude backend no longer shells out here; the orchestrator runs the
    # deterministic DAG in-process via ClaudeStageClient (python -m tradeloop.orchestrator
    # premarket --backend claude). This entrypoint is the OpenRouter/codex path only.
    echo "unknown TRADELOOP_AGENT: $TRADELOOP_AGENT (use codex)" >&2
    exit 2
    ;;
esac
