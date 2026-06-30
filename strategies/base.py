from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data.models import Bar, OrderRecord, Position, Signal


class BaseStrategy(ABC):
    """Unified strategy interface shared by backtest, paper, and testnet."""

    def __init__(self, name: str, symbol: str, timeframe: str, params: dict) -> None:
        self.name = name
        self.symbol = symbol
        self.timeframe = timeframe
        self.params = params
        self.bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> None:
        if bar.symbol.replace("/", "").upper() != self.symbol.replace("/", "").upper():
            return
        if bar.timeframe != self.timeframe:
            return
        self.bars.append(bar)

    def build_feature_rows(self) -> list[dict[str, Any]]:
        rows = [
            {
                "symbol": bar.symbol,
                "timeframe": bar.timeframe,
                "open_time": bar.open_time,
                "close_time": bar.close_time,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in self.bars
        ]
        rows = self.populate_indicators(rows)
        rows = self.populate_entry_trend(rows)
        rows = self.populate_exit_trend(rows)
        return rows

    def populate_indicators(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

    def populate_entry_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

    def populate_exit_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

    @abstractmethod
    def generate_signal(self, bar: Bar, position: Position | None) -> Signal:
        raise NotImplementedError

    def on_order_update(self, order: OrderRecord) -> None:
        """Hook for strategies that need order feedback; V1 keeps it lightweight."""
