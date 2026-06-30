from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.types import RiskStatus, human_symbol, normalize_symbol


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"
    HOLD = "HOLD"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True)
class Bar:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0
    trades: int = 0
    is_closed: bool = True
    source: str = "historical"

    @property
    def normalized_symbol(self) -> str:
        return normalize_symbol(self.symbol)


@dataclass(slots=True)
class Ticker:
    symbol: str
    timestamp: datetime
    price: float
    bid: float = 0.0
    ask: float = 0.0


@dataclass(slots=True)
class DepthSnapshot:
    symbol: str
    timestamp: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass(slots=True)
class Signal:
    strategy_name: str
    symbol: str
    timeframe: str
    signal_type: SignalType
    timestamp: datetime
    reason: str
    strength: float = 1.0
    stop_loss: float | None = None
    take_profit: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Balance:
    asset: str
    free: float
    locked: float = 0.0

    @property
    def total(self) -> float:
        return self.free + self.locked


@dataclass(slots=True)
class AccountSnapshot:
    timestamp: datetime
    balances: dict[str, Balance]
    net_asset_value: float
    available_quote_balance: float


@dataclass(slots=True)
class ExchangeRule:
    symbol: str
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float
    base_asset: str
    quote_asset: str


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    client_order_id: str
    idempotency_key: str
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reduce_only: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRecord:
    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    status: OrderStatus
    quantity: float
    price: float | None
    filled_quantity: float
    average_price: float | None
    created_at: datetime
    updated_at: datetime
    mode: str
    reduce_only: bool = False
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FillRecord:
    fill_id: str
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    fee_asset: str
    realized_pnl: float
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    market_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    def update_mark(self, price: float) -> None:
        self.market_price = price
        if self.quantity > 0:
            self.unrealized_pnl = (price - self.average_price) * self.quantity
        else:
            self.unrealized_pnl = 0.0
        self.updated_at = utc_now()


@dataclass(slots=True)
class PnLSnapshot:
    date: str
    realized_pnl: float
    unrealized_pnl: float
    net_asset_value: float


@dataclass(slots=True)
class RiskEvent:
    timestamp: datetime
    event_type: str
    message: str
    status: RiskStatus
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PricePoint:
    timestamp: datetime
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class EquityPoint:
    timestamp: datetime
    net_asset_value: float
    realized_pnl: float
    unrealized_pnl: float
    session_pnl: float


@dataclass(slots=True)
class OrderTimelineEvent:
    timestamp: datetime
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    message: str
    strategy_name: str = ""


@dataclass(slots=True)
class ConnectionEvent:
    timestamp: datetime
    channel: str
    state: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def serialize_dataclass(value: Any) -> dict[str, Any]:
    payload = asdict(value)
    for key, raw in list(payload.items()):
        if isinstance(raw, Enum):
            payload[key] = raw.value
        elif isinstance(raw, datetime):
            payload[key] = raw.isoformat()
    return payload


def display_symbol(symbol: str) -> str:
    return human_symbol(symbol)
