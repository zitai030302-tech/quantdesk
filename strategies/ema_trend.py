from __future__ import annotations

from typing import Any

from data.models import Bar, Position, Signal, SignalType
from strategies.base import BaseStrategy
from strategies.indicators import atr, ema


class EMATrendStrategy(BaseStrategy):
    """
    保守型 EMA 趋势跟随策略。

    只有当快线 EMA 上穿慢线 EMA，且当前没有多头持仓时才会开仓。
    当快线下穿慢线时触发离场。止损止盈不在策略里写死，而是交给
    风控层根据 ATR 自动计算，方便后续统一调参。
    """

    def populate_indicators(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        closes = [float(item["close"]) for item in rows]
        fast_period = int(self.params.get("fast_period", 9))
        slow_period = int(self.params.get("slow_period", 21))
        atr_period = int(self.params.get("atr_period", 14))

        fast_values = ema(closes, fast_period)
        slow_values = ema(closes, slow_period)
        atr_values = atr(self.bars, atr_period)
        enriched: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            updated = dict(row)
            updated["fast_ema"] = fast_values[index]
            updated["slow_ema"] = slow_values[index]
            updated["atr"] = atr_values[index]
            enriched.append(updated)
        return enriched

    def populate_entry_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        min_trend_strength = float(self.params.get("min_trend_strength", 0.0))
        enriched: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            updated = dict(row)
            updated["enter_long"] = False
            updated["entry_reason"] = ""
            if index >= 1:
                previous = rows[index - 1]
                fast_now = updated.get("fast_ema")
                slow_now = updated.get("slow_ema")
                fast_prev = previous.get("fast_ema")
                slow_prev = previous.get("slow_ema")
                if None not in {fast_now, slow_now, fast_prev, slow_prev}:
                    trend_strength = abs((fast_now or 0.0) - (slow_now or 0.0)) / float(updated["close"])
                    if fast_prev <= slow_prev and fast_now > slow_now and trend_strength >= min_trend_strength:
                        updated["enter_long"] = True
                        updated["entry_reason"] = "快线 EMA 上穿慢线 EMA"
            enriched.append(updated)
        return enriched

    def populate_exit_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            updated = dict(row)
            updated["exit_long"] = False
            updated["exit_reason"] = ""
            if index >= 1:
                previous = rows[index - 1]
                fast_now = updated.get("fast_ema")
                slow_now = updated.get("slow_ema")
                fast_prev = previous.get("fast_ema")
                slow_prev = previous.get("slow_ema")
                if None not in {fast_now, slow_now, fast_prev, slow_prev} and fast_prev >= slow_prev and fast_now < slow_now:
                    updated["exit_long"] = True
                    updated["exit_reason"] = "快线 EMA 下穿慢线 EMA"
            enriched.append(updated)
        return enriched

    def generate_signal(self, bar: Bar, position: Position | None) -> Signal:
        rows = self.build_feature_rows()
        index = len(rows) - 1
        reason = "EMA 指标预热不足"
        signal_type = SignalType.HOLD

        if index >= 0:
            latest = rows[index]
            if latest.get("enter_long"):
                signal_type = SignalType.BUY if not (position and position.is_open) else SignalType.HOLD
                reason = str(latest.get("entry_reason") or "快线 EMA 上穿慢线 EMA")
            elif latest.get("exit_long"):
                signal_type = SignalType.FLAT if position and position.is_open else SignalType.HOLD
                reason = str(latest.get("exit_reason") or "快线 EMA 下穿慢线 EMA")
            elif latest.get("fast_ema") is not None and latest.get("slow_ema") is not None:
                reason = "当前没有出现 EMA 交叉信号"
            else:
                reason = "EMA 指标预热不足"

        return Signal(
            strategy_name=self.name,
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            signal_type=signal_type,
            timestamp=bar.close_time,
            reason=reason,
            metadata={
                "atr": rows[index].get("atr") if index >= 0 else None,
                "fast_ema": rows[index].get("fast_ema") if index >= 0 else None,
                "slow_ema": rows[index].get("slow_ema") if index >= 0 else None,
                "enter_long": rows[index].get("enter_long") if index >= 0 else False,
                "exit_long": rows[index].get("exit_long") if index >= 0 else False,
            },
        )
