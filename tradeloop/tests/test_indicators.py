from tradeloop.lib.ta.indicators import adx, atr, bollinger_bands, ema, macd, rsi, vwap
from tradeloop.lib.ta.patterns import breakout, volume_spike


def test_indicators_return_expected_shapes() -> None:
    closes = [float(value) for value in range(1, 60)]
    highs = [value + 1 for value in closes]
    lows = [value - 1 for value in closes]
    volumes = [1000.0 for _ in closes]

    assert len(ema(closes, 20)) == len(closes)
    assert len(rsi(closes, 14)) == len(closes)
    assert len(macd(closes)["macd"]) == len(closes)
    assert len(atr(highs, lows, closes, 14)) == len(closes)
    assert len(vwap(highs, lows, closes, volumes)) == len(closes)
    assert len(adx(highs, lows, closes, 14)) == len(closes)
    assert len(bollinger_bands(closes, 20)["upper"]) == len(closes)


def test_bullish_patterns() -> None:
    assert breakout([10, 11, 12, 13, 20], lookback=3).bullish
    assert volume_spike([100] * 20 + [250], lookback=20, multiple=2).bullish

