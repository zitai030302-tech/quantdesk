from __future__ import annotations

import math

from data.models import Bar


def sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        window = values[index + 1 - period : index + 1]
        result.append(sum(window) / period)
    return result


def ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    if not values:
        return result
    multiplier = 2 / (period + 1)
    ema_value: float | None = None
    seed = sma(values, period)
    for index, value in enumerate(values):
        if index + 1 < period:
            result.append(None)
            continue
        if ema_value is None:
            ema_value = seed[index]
        else:
            ema_value = ((value - ema_value) * multiplier) + ema_value
        result.append(ema_value)
    return result


def rolling_std(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        window = values[index + 1 - period : index + 1]
        mean = sum(window) / period
        variance = sum((item - mean) ** 2 for item in window) / period
        result.append(math.sqrt(variance))
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rs = avg_gain / avg_loss if avg_loss else float("inf")
    result[period] = 100 - (100 / (1 + rs))

    for index in range(period + 1, len(values)):
        gain = gains[index - 1]
        loss = losses[index - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        result[index] = 100 - (100 / (1 + rs))
    return result


def bollinger_bands(values: list[float], period: int = 20, stddev: float = 2.0) -> list[tuple[float | None, float | None, float | None]]:
    middle = sma(values, period)
    std = rolling_std(values, period)
    bands: list[tuple[float | None, float | None, float | None]] = []
    for mid, dev in zip(middle, std):
        if mid is None or dev is None:
            bands.append((None, None, None))
        else:
            bands.append((mid + dev * stddev, mid, mid - dev * stddev))
    return bands


def true_ranges(bars: list[Bar]) -> list[float]:
    result: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            result.append(bar.high - bar.low)
            continue
        previous_close = bars[index - 1].close
        result.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return result


def atr(bars: list[Bar], period: int = 14) -> list[float | None]:
    trs = true_ranges(bars)
    result: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return result
    initial = sum(trs[:period]) / period
    result[period - 1] = initial
    current = initial
    for index in range(period, len(trs)):
        current = ((current * (period - 1)) + trs[index]) / period
        result[index] = current
    return result
