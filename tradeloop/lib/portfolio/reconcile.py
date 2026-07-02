from tradeloop.lib.portfolio.state import PortfolioState


def compare_paper_live(paper: PortfolioState, live: PortfolioState) -> list[str]:
    issues: list[str] = []
    symbols = set(paper.positions) | set(live.positions)
    for symbol in sorted(symbols):
        if paper.positions.get(symbol, 0) != live.positions.get(symbol, 0):
            issues.append(f"{symbol}: paper={paper.positions.get(symbol, 0)} live={live.positions.get(symbol, 0)}")
    return issues

