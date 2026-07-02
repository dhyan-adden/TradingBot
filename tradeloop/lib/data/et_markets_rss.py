from tradeloop.lib.data.google_news_rss import NewsItem, fetch_google_news


def fetch_et_markets(query: str = "Economic Times Markets NSE stocks", limit: int = 10) -> list[NewsItem]:
    return fetch_google_news(query, limit=limit)
