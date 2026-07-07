"""Thin compat shim. The real reconciler lives in tradeloop.lib.audit.reconcile.

# ponytail: legacy compare_paper_live kept for its old import path; new code
# imports compare from lib.audit.reconcile. Delete compare_paper_live once no
# caller references it.
"""
from tradeloop.lib.audit.reconcile import compare  # re-export
from tradeloop.lib.portfolio.state import PortfolioState

__all__ = ["compare", "compare_paper_live"]


def compare_paper_live(paper: PortfolioState, live: PortfolioState) -> list[str]:
    issues: list[str] = []
    symbols = set(paper.positions) | set(live.positions)
    for symbol in sorted(symbols):
        if paper.positions.get(symbol, 0) != live.positions.get(symbol, 0):
            issues.append(f"{symbol}: paper={paper.positions.get(symbol, 0)} live={live.positions.get(symbol, 0)}")
    return issues
