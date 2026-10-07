from __future__ import annotations

import math
import re


def periods_per_year(timeframe: str) -> int:
    """Annualization for fixed-size bars in a 24/7 crypto market."""
    match = re.fullmatch(r"([1-9][0-9]*)([mhdw])", timeframe)
    if not match:
        raise ValueError("timeframe must use positive minutes, hours, days, or weeks")
    count, unit = int(match.group(1)), match.group(2)
    minutes = count * {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit]
    return max(1, int(365 * 24 * 60 / minutes))


def max_drawdown(equity_curve: list[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = min(drawdown, (equity - peak) / peak)
    return abs(drawdown)


def sharpe_ratio(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / len(returns)
    stddev = math.sqrt(variance)
    if stddev == 0:
        return 0.0
    return (mean / stddev) * math.sqrt(periods_per_year)


def win_rate(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    wins = sum(1 for pnl in trade_pnls if pnl > 0)
    return wins / len(trade_pnls)

