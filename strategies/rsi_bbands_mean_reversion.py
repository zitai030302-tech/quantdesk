from __future__ import annotations

from typing import Any

from data.models import Bar, Position, Signal, SignalType
from strategies.base import BaseStrategy
from strategies.indicators import atr, bollinger_bands, rsi


class RSIBBandsMeanReversionStrategy(BaseStrategy):
    """
    使用 RSI 与布林带的均值回归策略。

    当价格收在布林下轨下方且 RSI 进入超卖区时尝试做多。
    已有多头持仓时，若价格回到中轨附近或 RSI 回归正常区间，则触发平仓。
    """

    def populate_indicators(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        closes = [float(item["close"]) for item in rows]
        rsi_period = int(self.params.get("rsi_period", 14))
        bb_period = int(self.params.get("bb_period", 20))
        bb_stddev = float(self.params.get("bb_stddev", 2.0))

        rsi_values = rsi(closes, rsi_period)
        bands = bollinger_bands(closes, bb_period, bb_stddev)
        atr_values = atr(self.bars, 14)

        enriched: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            upper, middle, lower = bands[index]
            updated = dict(row)
            updated["rsi"] = rsi_values[index]
            updated["upper_band"] = upper
            updated["middle_band"] = middle
            updated["lower_band"] = lower
            updated["atr"] = atr_values[index]
            enriched.append(updated)
        return enriched

    def populate_entry_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        oversold = float(self.params.get("rsi_oversold", 28))
        enriched: list[dict[str, Any]] = []
        for row in rows:
            updated = dict(row)
            updated["enter_long"] = False
            updated["entry_reason"] = ""
            if updated.get("lower_band") is not None and updated.get("rsi") is not None:
                if float(updated["close"]) <= float(updated["lower_band"]) and float(updated["rsi"]) <= oversold:
                    updated["enter_long"] = True
                    updated["entry_reason"] = "价格跌破下轨，且 RSI 进入超卖区"
            enriched.append(updated)
        return enriched

    def populate_exit_trend(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        overbought = float(self.params.get("rsi_overbought", 72))
        exit_at_midline = bool(self.params.get("exit_at_midline", True))
        enriched: list[dict[str, Any]] = []
        for row in rows:
            updated = dict(row)
            updated["exit_long"] = False
            updated["exit_reason"] = ""
            current_rsi = updated.get("rsi")
            middle = updated.get("middle_band")
            upper = updated.get("upper_band")
            if middle is not None and exit_at_midline and float(updated["close"]) >= float(middle):
                updated["exit_long"] = True
                updated["exit_reason"] = "价格回归到布林中轨附近"
            elif upper is not None and current_rsi is not None and float(updated["close"]) >= float(upper) and float(current_rsi) >= overbought:
                updated["exit_long"] = True
                updated["exit_reason"] = "价格触及上轨，且 RSI 进入超买区"
            enriched.append(updated)
        return enriched

    def generate_signal(self, bar: Bar, position: Position | None) -> Signal:
        rows = self.build_feature_rows()
        index = len(rows) - 1
        signal_type = SignalType.HOLD
        reason = "指标预热不足"

        if index >= 0:
            latest = rows[index]
            if latest.get("enter_long") and not (position and position.is_open):
                signal_type = SignalType.BUY
                reason = str(latest.get("entry_reason") or "价格跌破下轨，且 RSI 进入超卖区")
            elif position and position.is_open:
                if latest.get("exit_long"):
                    signal_type = SignalType.FLAT
                    reason = str(latest.get("exit_reason") or "价格回归到布林中轨附近")
                elif latest.get("middle_band") is not None and latest.get("upper_band") is not None and latest.get("rsi") is not None:
                    reason = "等待均值回归离场"
                else:
                    reason = "指标预热不足"
            elif latest.get("lower_band") is not None and latest.get("upper_band") is not None and latest.get("middle_band") is not None and latest.get("rsi") is not None:
                reason = "当前没有均值回归开仓条件"
            else:
                reason = "指标预热不足"

        return Signal(
            strategy_name=self.name,
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            signal_type=signal_type,
            timestamp=bar.close_time,
            reason=reason,
            metadata={
                "upper_band": rows[index].get("upper_band") if index >= 0 else None,
                "middle_band": rows[index].get("middle_band") if index >= 0 else None,
                "lower_band": rows[index].get("lower_band") if index >= 0 else None,
                "rsi": rows[index].get("rsi") if index >= 0 else None,
                "atr": rows[index].get("atr") if index >= 0 else None,
                "enter_long": rows[index].get("enter_long") if index >= 0 else False,
                "exit_long": rows[index].get("exit_long") if index >= 0 else False,
            },
        )
