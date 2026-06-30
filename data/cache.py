from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from data.models import (
    AccountSnapshot,
    Bar,
    ConnectionEvent,
    EquityPoint,
    FillRecord,
    OrderRecord,
    OrderTimelineEvent,
    Position,
    PricePoint,
    RiskEvent,
    Signal,
    utc_now,
)


@dataclass(slots=True)
class RuntimeCache:
    latest_bars: dict[tuple[str, str], Bar] = field(default_factory=dict)
    price_history: dict[str, deque[PricePoint]] = field(default_factory=dict)
    account_snapshot: AccountSnapshot | None = None
    balances: dict[str, float] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    open_orders: dict[str, OrderRecord] = field(default_factory=dict)
    recent_signals: deque[Signal] = field(default_factory=lambda: deque(maxlen=50))
    recent_orders: deque[OrderRecord] = field(default_factory=lambda: deque(maxlen=50))
    recent_fills: deque[FillRecord] = field(default_factory=lambda: deque(maxlen=50))
    order_timeline: deque[OrderTimelineEvent] = field(default_factory=lambda: deque(maxlen=120))
    connection_events: deque[ConnectionEvent] = field(default_factory=lambda: deque(maxlen=80))
    equity_history: deque[EquityPoint] = field(default_factory=lambda: deque(maxlen=240))
    risk_events: deque[RiskEvent] = field(default_factory=lambda: deque(maxlen=50))
    session_start_nav: float | None = None

    def store_bar(self, bar: Bar) -> None:
        self.latest_bars[(bar.normalized_symbol, bar.timeframe)] = bar
        key = f"{bar.normalized_symbol}|{bar.timeframe}"
        series = self.price_history.setdefault(key, deque(maxlen=240))
        series.append(
            PricePoint(
                timestamp=bar.close_time,
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
        )

    def latest_bar(self, symbol: str, timeframe: str) -> Bar | None:
        key = (symbol.replace("/", "").upper(), timeframe)
        return self.latest_bars.get(key)

    def record_equity(self, snapshot: AccountSnapshot, realized_pnl: float, unrealized_pnl: float) -> None:
        if self.session_start_nav is None:
            self.session_start_nav = snapshot.net_asset_value
        self.equity_history.append(
            EquityPoint(
                timestamp=snapshot.timestamp,
                net_asset_value=snapshot.net_asset_value,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                session_pnl=snapshot.net_asset_value - self.session_start_nav,
            )
        )

    def record_order_event(self, order: OrderRecord, message: str) -> None:
        event = OrderTimelineEvent(
            timestamp=order.updated_at,
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side.value,
            status=order.status.value,
            message=message,
            strategy_name=str(order.metadata.get("strategy", "")),
        )
        if self.order_timeline:
            latest = self.order_timeline[-1]
            if latest.order_id == event.order_id and latest.status == event.status and latest.message == event.message:
                return
        self.order_timeline.append(event)

    def record_connection_event(self, channel: str, state: str, message: str, details: dict | None = None) -> None:
        event = ConnectionEvent(
            timestamp=utc_now(),
            channel=channel,
            state=state,
            message=message,
            details=details or {},
        )
        self.connection_events.append(event)
