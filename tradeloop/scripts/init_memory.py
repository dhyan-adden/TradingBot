#!/usr/bin/env python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


FILES = {
    "memory/lessons_learned.md": "# Lessons Learned\n",
    "memory/manager_feedback.md": "# Manager Feedback\n",
    "memory/trade_journal.md": "# Trade Journal\n",
    "memory/strategy_performance.md": (
        "# Strategy Performance\n\n"
        "live_ready: false\n"
        "paper_trades: 0\n\n"
        "| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |\n"
        "| --- | ---: | ---: | ---: | ---: | --- |\n"
    ),
    "memory/macro_view.md": "# Macro View\n",
}


def main() -> int:
    for relative, content in FILES.items():
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    (ROOT / "memory" / "stock_dossiers").mkdir(parents=True, exist_ok=True)
    (ROOT / "memory" / "debate_archive").mkdir(parents=True, exist_ok=True)
    print("tradeloop_memory=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
