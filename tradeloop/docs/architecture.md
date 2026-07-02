# Architecture

```text
cron
  -> scripts/run_cycle.sh <mode>
    -> python preprocessing
       -> 00_context.md
       -> 01_news_raw.md
       -> 02_setups_raw.md
    -> Codex CLI master orchestrator (OpenRouter provider)
       -> minimax/minimax-m3 for master orchestration
       -> analyst files
       -> shortlist
       -> bull/bear debate
       -> trade plan
       -> risk report
       -> PM decision + orders.json
    -> broker router
       -> kill_switch check
       -> paper broker OR Zerodha MCP payload
       -> fills.json
    -> post-trade analyst
       -> trade journal
       -> lessons
       -> strategy performance
       -> dossiers
```

Every boundary is a file boundary. Python never calls an LLM. Codex never reads
`.env`.

Team model assignments live in
`tradeloop/prompts/shared/model_routing.md`. All reasoning runs through
OpenRouter using only four models (DeepSeek V4 Flash, MiMo-V2.5, MiniMax M3,
Hy3 preview); the master orchestrator uses MiniMax M3.
