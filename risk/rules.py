from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.types import RiskStatus, RuntimeMode


@dataclass(slots=True)
class DailyRiskState:
    trade_date: date
    realized_pnl: float = 0.0
    loss_streak: int = 0
    starting_nav: float = 0.0


def ensure_safe_mode(mode: RuntimeMode, allow_live: bool) -> tuple[bool, str]:
    if mode == RuntimeMode.LIVE_DISABLED and not allow_live:
        return False, "默认禁止实盘模式"
    return True, ""


def check_daily_loss_limit(state: DailyRiskState, current_nav: float, daily_loss_limit_pct: float) -> tuple[bool, str]:
    baseline = state.starting_nav or current_nav
    if baseline <= 0:
        return True, ""
    drawdown_pct = abs(min(0.0, state.realized_pnl)) / baseline
    if drawdown_pct >= daily_loss_limit_pct:
        return False, f"已触发单日亏损上限：{drawdown_pct:.2%}"
    return True, ""


def check_loss_streak(state: DailyRiskState, max_loss_streak: int) -> tuple[bool, str]:
    if state.loss_streak >= max_loss_streak:
        return False, f"连续亏损次数达到限制：{state.loss_streak}"
    return True, ""


def derive_status(protect: bool, paused: bool) -> RiskStatus:
    if protect:
        return RiskStatus.PROTECT
    if paused:
        return RiskStatus.PAUSED
    return RiskStatus.ACTIVE


def trading_day(now: datetime) -> date:
    return now.date()
