from typing import Iterable, List, Sequence


def _series(values: Iterable[float]) -> List[float]:
    return [float(value) for value in values]


def sma(values: Sequence[float], period: int) -> List[float | None]:
    data = _series(values)
    if period <= 0:
        raise ValueError("period must be positive")
    result: List[float | None] = []
    for index in range(len(data)):
        if index + 1 < period:
            result.append(None)
            continue
        window = data[index + 1 - period : index + 1]
        result.append(sum(window) / period)
    return result


def ema(values: Sequence[float], period: int) -> List[float | None]:
    data = _series(values)
    if period <= 0:
        raise ValueError("period must be positive")
    if not data:
        return []
    alpha = 2 / (period + 1)
    result: List[float | None] = []
    current: float | None = None
    for index, value in enumerate(data):
        if index + 1 < period:
            result.append(None)
            continue
        if current is None:
            current = sum(data[index + 1 - period : index + 1]) / period
        else:
            current = (value * alpha) + (current * (1 - alpha))
        result.append(current)
    return result


def rsi(values: Sequence[float], period: int = 14) -> List[float | None]:
    data = _series(values)
    if period <= 0:
        raise ValueError("period must be positive")
    if len(data) < period + 1:
        return [None] * len(data)
    result: List[float | None] = [None] * period
    gains: List[float] = []
    losses: List[float] = []
    for index in range(1, period + 1):
        change = data[index] - data[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result.append(_rsi_value(avg_gain, avg_loss))
    for index in range(period + 1, len(data)):
        change = data[index] - data[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result.append(_rsi_value(avg_gain, avg_loss))
    return result


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, List[float | None]]:
    if fast >= slow:
        raise ValueError("fast period must be less than slow period")
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    line: List[float | None] = []
    for fast_value, slow_value in zip(fast_ema, slow_ema):
        line.append(None if fast_value is None or slow_value is None else fast_value - slow_value)
    signal_input = [0.0 if value is None else value for value in line]
    raw_signal = ema(signal_input, signal)
    signal_line: List[float | None] = []
    histogram: List[float | None] = []
    for macd_value, signal_value in zip(line, raw_signal):
        if macd_value is None or signal_value is None:
            signal_line.append(None)
            histogram.append(None)
        else:
            signal_line.append(signal_value)
            histogram.append(macd_value - signal_value)
    return {"macd": line, "signal": signal_line, "histogram": histogram}


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> List[float | None]:
    high = _series(highs)
    low = _series(lows)
    close = _series(closes)
    if not (len(high) == len(low) == len(close)):
        raise ValueError("highs, lows, and closes must have equal length")
    true_ranges: List[float] = []
    for index in range(len(close)):
        if index == 0:
            true_ranges.append(high[index] - low[index])
            continue
        true_ranges.append(max(high[index] - low[index], abs(high[index] - close[index - 1]), abs(low[index] - close[index - 1])))
    return sma(true_ranges, period)


def vwap(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float]) -> List[float | None]:
    high = _series(highs)
    low = _series(lows)
    close = _series(closes)
    volume = _series(volumes)
    if not (len(high) == len(low) == len(close) == len(volume)):
        raise ValueError("price and volume series must have equal length")
    cumulative_price_volume = 0.0
    cumulative_volume = 0.0
    result: List[float | None] = []
    for h, l, c, v in zip(high, low, close, volume):
        typical = (h + l + c) / 3
        cumulative_price_volume += typical * v
        cumulative_volume += v
        result.append(None if cumulative_volume == 0 else cumulative_price_volume / cumulative_volume)
    return result


def bollinger_bands(values: Sequence[float], period: int = 20, stddev: float = 2.0) -> dict[str, List[float | None]]:
    data = _series(values)
    middle = sma(data, period)
    upper: List[float | None] = []
    lower: List[float | None] = []
    for index, mid in enumerate(middle):
        if mid is None:
            upper.append(None)
            lower.append(None)
            continue
        window = data[index + 1 - period : index + 1]
        variance = sum((value - mid) ** 2 for value in window) / period
        band = (variance ** 0.5) * stddev
        upper.append(mid + band)
        lower.append(mid - band)
    return {"middle": middle, "upper": upper, "lower": lower}


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> List[float | None]:
    high = _series(highs)
    low = _series(lows)
    close = _series(closes)
    if not (len(high) == len(low) == len(close)):
        raise ValueError("highs, lows, and closes must have equal length")
    if len(close) < period + 1:
        return [None] * len(close)
    plus_dm = [0.0]
    minus_dm = [0.0]
    tr = [high[0] - low[0]]
    for index in range(1, len(close)):
        up_move = high[index] - high[index - 1]
        down_move = low[index - 1] - low[index]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr.append(max(high[index] - low[index], abs(high[index] - close[index - 1]), abs(low[index] - close[index - 1])))
    atr_values = sma(tr, period)
    plus_di: List[float | None] = []
    minus_di: List[float | None] = []
    for index, average_tr in enumerate(atr_values):
        if average_tr is None or average_tr == 0 or index + 1 < period:
            plus_di.append(None)
            minus_di.append(None)
            continue
        plus_avg = sum(plus_dm[index + 1 - period : index + 1]) / period
        minus_avg = sum(minus_dm[index + 1 - period : index + 1]) / period
        plus_di.append(100 * plus_avg / average_tr)
        minus_di.append(100 * minus_avg / average_tr)
    dx: List[float] = []
    result: List[float | None] = []
    for pdi, mdi in zip(plus_di, minus_di):
        if pdi is None or mdi is None or pdi + mdi == 0:
            result.append(None)
            continue
        current_dx = 100 * abs(pdi - mdi) / (pdi + mdi)
        dx.append(current_dx)
        result.append(None if len(dx) < period else sum(dx[-period:]) / period)
    return result


def add_indicators(frame, close_col: str = "Close"):
    """Return a copy of a pandas DataFrame with standard indicator columns."""

    data = frame.copy()
    closes = [float(value) for value in data[close_col].tolist()]
    data["EMA9"] = ema(closes, 9)
    data["EMA20"] = ema(closes, 20)
    data["EMA50"] = ema(closes, 50)
    data["EMA200"] = ema(closes, 200)
    data["RSI14"] = rsi(closes, 14)
    macd_values = macd(closes)
    data["MACD"] = macd_values["macd"]
    data["MACDSignal"] = macd_values["signal"]
    data["MACDHistogram"] = macd_values["histogram"]
    if {"High", "Low", "Close"}.issubset(data.columns):
        highs = [float(value) for value in data["High"].tolist()]
        lows = [float(value) for value in data["Low"].tolist()]
        data["ATR14"] = atr(highs, lows, closes, 14)
        data["ADX14"] = adx(highs, lows, closes, 14)
        if "Volume" in data.columns:
            volumes = [float(value) for value in data["Volume"].tolist()]
            data["VWAP"] = vwap(highs, lows, closes, volumes)
    bands = bollinger_bands(closes, 20, 2)
    data["BBMiddle"] = bands["middle"]
    data["BBUpper"] = bands["upper"]
    data["BBLower"] = bands["lower"]
    return data
