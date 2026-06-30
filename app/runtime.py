from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.types import RuntimeMode
from data.models import (
    AccountSnapshot,
    ConnectionEvent,
    EquityPoint,
    FillRecord,
    OrderRecord,
    OrderTimelineEvent,
    Position,
    PricePoint,
    RiskEvent,
    Signal,
)


@dataclass(slots=True)
class RuntimeSnapshot:
    mode: RuntimeMode
    connection_status: str
    active_strategy: str = ""
    tracked_symbols: list[str] = field(default_factory=list)
    tracked_timeframes: list[str] = field(default_factory=list)
    market_board: dict[str, Any] = field(default_factory=dict)
    network_diagnostics: dict[str, Any] = field(default_factory=dict)
    trade_plans: list[dict[str, Any]] = field(default_factory=list)
    control_state: dict[str, Any] = field(default_factory=dict)
    account: AccountSnapshot | None = None
    positions: dict[str, Position] = field(default_factory=dict)
    recent_signals: list[Signal] = field(default_factory=list)
    recent_orders: list[OrderRecord] = field(default_factory=list)
    recent_fills: list[FillRecord] = field(default_factory=list)
    order_timeline: list[OrderTimelineEvent] = field(default_factory=list)
    connection_events: list[ConnectionEvent] = field(default_factory=list)
    price_history: dict[str, list[PricePoint]] = field(default_factory=dict)
    equity_history: list[EquityPoint] = field(default_factory=list)
    risk_events: list[RiskEvent] = field(default_factory=list)
    risk_state: dict = field(default_factory=dict)


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(raw) for key, raw in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _serialize(raw) for key, raw in value.__dict__.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _serialize(getattr(value, key))
            for key in value.__dataclass_fields__.keys()
        }
    return value


def runtime_snapshot_to_dict(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    return {
        "mode": snapshot.mode.value,
        "connection_status": snapshot.connection_status,
        "active_strategy": snapshot.active_strategy,
        "tracked_symbols": _serialize(snapshot.tracked_symbols),
        "tracked_timeframes": _serialize(snapshot.tracked_timeframes),
        "market_board": _serialize(snapshot.market_board),
        "network_diagnostics": _serialize(snapshot.network_diagnostics),
        "trade_plans": _serialize(snapshot.trade_plans),
        "control_state": _serialize(snapshot.control_state),
        "account": _serialize(snapshot.account) if snapshot.account else None,
        "positions": _serialize(snapshot.positions),
        "recent_signals": _serialize(snapshot.recent_signals),
        "recent_orders": _serialize(snapshot.recent_orders),
        "recent_fills": _serialize(snapshot.recent_fills),
        "order_timeline": _serialize(snapshot.order_timeline),
        "connection_events": _serialize(snapshot.connection_events),
        "price_history": _serialize(snapshot.price_history),
        "equity_history": _serialize(snapshot.equity_history),
        "risk_events": _serialize(snapshot.risk_events),
        "risk_state": _serialize(snapshot.risk_state),
    }
