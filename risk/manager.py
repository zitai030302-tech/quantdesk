from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.types import RiskConfig, RiskStatus, RuntimeMode
from data.models import AccountSnapshot, Bar, ExchangeRule, FillRecord, Position, RiskEvent, Signal, SignalType, utc_now
from risk.protect_mode import ProtectModeState
from risk.rules import DailyRiskState, check_daily_loss_limit, check_loss_streak, ensure_safe_mode, trading_day
from risk.sizing import PositionSizer
from strategies.indicators import atr


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reasons: list[str]
    quantity: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None


class RiskManager:
    def __init__(self, config: RiskConfig, mode: RuntimeMode) -> None:
        self.config = config
        self.mode = mode
        self.protect_mode = ProtectModeState()
        self.state = DailyRiskState(trade_date=trading_day(utc_now()))
        self.events: list[RiskEvent] = []

    def _roll_day(self, snapshot: AccountSnapshot) -> None:
        today = trading_day(snapshot.timestamp)
        if today != self.state.trade_date:
            self.state = DailyRiskState(
                trade_date=today,
                realized_pnl=0.0,
                loss_streak=0,
                starting_nav=snapshot.net_asset_value,
            )
        elif self.state.starting_nav <= 0:
            self.state.starting_nav = snapshot.net_asset_value

    def risk_status(self) -> RiskStatus:
        return self.protect_mode.status

    def latest_reason(self) -> str:
        return self.protect_mode.reason

    def enter_protect_mode(self, reason: str, details: dict[str, Any] | None = None) -> RiskEvent:
        event = RiskEvent(
            timestamp=utc_now(),
            event_type="protect_mode",
            message=reason,
            status=RiskStatus.PROTECT,
            details=details or {},
        )
        self.protect_mode.activate(reason, event.timestamp)
        self.events.append(event)
        return event

    def pause_trading(self, reason: str, details: dict[str, Any] | None = None) -> RiskEvent:
        event = RiskEvent(
            timestamp=utc_now(),
            event_type="pause",
            message=reason,
            status=RiskStatus.PAUSED,
            details=details or {},
        )
        self.protect_mode.pause(reason, event.timestamp)
        self.events.append(event)
        return event

    def clear_pause(self) -> None:
        self.protect_mode.clear()

    def evaluate_signal(
        self,
        signal: Signal,
        account: AccountSnapshot,
        position: Position | None,
        rule: ExchangeRule,
        bar_history: list[Bar],
    ) -> RiskDecision:
        self._roll_day(account)
        allowed, reason = ensure_safe_mode(self.mode, self.config.allow_live)
        if not allowed:
            return RiskDecision(False, [reason])

        if self.protect_mode.status == RiskStatus.PROTECT:
            return RiskDecision(False, [f"当前处于保护模式：{self.protect_mode.reason}"])
        if self.protect_mode.status == RiskStatus.PAUSED and signal.signal_type == SignalType.BUY:
            return RiskDecision(False, [f"交易已暂停：{self.protect_mode.reason}"])

        if signal.signal_type in {SignalType.HOLD}:
            return RiskDecision(False, ["策略当前给出观望信号"], 0.0)

        daily_ok, daily_reason = check_daily_loss_limit(
            self.state,
            account.net_asset_value,
            self.config.daily_loss_limit_pct,
        )
        if not daily_ok and signal.signal_type == SignalType.BUY:
            return RiskDecision(False, [daily_reason])

        streak_ok, streak_reason = check_loss_streak(self.state, self.config.max_loss_streak)
        if not streak_ok and signal.signal_type == SignalType.BUY:
            return RiskDecision(False, [streak_reason])

        if signal.signal_type == SignalType.BUY and position and position.is_open:
            return RiskDecision(False, ["当前已有多头持仓，禁止重复开仓"])

        if signal.signal_type in {SignalType.FLAT, SignalType.SELL}:
            if not position or not position.is_open:
                return RiskDecision(False, ["当前没有可减仓或平仓的多头持仓"])
            return RiskDecision(True, [], quantity=position.quantity)

        if len(bar_history) < self.config.atr_period:
            return RiskDecision(False, ["ATR 指标预热不足"])

        atr_values = atr(bar_history, self.config.atr_period)
        atr_value = atr_values[-1]
        if atr_value is None or atr_value <= 0:
            return RiskDecision(False, ["ATR 指标不可用"])

        entry = bar_history[-1].close
        stop_loss = entry - atr_value * self.config.atr_stop_mult
        take_profit = entry + atr_value * self.config.atr_take_profit_mult
        quantity = PositionSizer.size_from_risk(
            net_asset_value=account.net_asset_value,
            available_quote=account.available_quote_balance,
            risk_pct=self.config.max_trade_risk_pct,
            entry_price=entry,
            stop_loss=stop_loss,
            rule=rule,
            fee_rate=0.001,
            slippage_bps=self.config.slippage_bps,
        )
        if quantity <= 0:
            return RiskDecision(False, ["仓位规模低于交易所最小限制，或可用余额不足"])
        return RiskDecision(True, [], quantity=quantity, stop_loss=stop_loss, take_profit=take_profit)

    def on_trade_closed(self, fill: FillRecord) -> RiskEvent | None:
        self.state.realized_pnl += fill.realized_pnl
        if fill.realized_pnl < 0:
            self.state.loss_streak += 1
            if self.state.loss_streak >= self.config.max_loss_streak:
                return self.pause_trading("连续亏损次数达到上限", {"loss_streak": self.state.loss_streak})
        else:
            self.state.loss_streak = 0
        return None

    def snapshot(self, account: AccountSnapshot, positions: dict[str, Position]) -> dict[str, Any]:
        return {
            "status": self.protect_mode.status.value,
            "reason": self.protect_mode.reason,
            "loss_streak": self.state.loss_streak,
            "daily_realized_pnl": self.state.realized_pnl,
            "net_asset_value": account.net_asset_value,
            "open_positions": sum(1 for pos in positions.values() if pos.is_open),
        }
