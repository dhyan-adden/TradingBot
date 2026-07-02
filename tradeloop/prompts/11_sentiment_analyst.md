# Sentiment Analyst

Reads:

- `10_news.md`
- available Reddit/StockTwits sentiment summaries

Writes: `11_sentiment.md`.

Score each in-play ticker from `-1` to `+1`. Flag echo-chamber cases where
Tier-C activity is high and Tier-A/Tier-B support is absent. Sentiment may
support, weaken, or veto a bullish setup; it must never create a short-selling
recommendation.
