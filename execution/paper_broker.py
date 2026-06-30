from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast
from uuid import uuid4

from app.types import normalize_symbol
from data.models import (
    AccountSnapshot,
    Balance,
    Bar,
    ExchangeRule,
    FillRecord,
    OrderRecord,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    utc_now,
)
from execution.adapter_base import ExchangeAdapter
from execution.validators import round_to_step


class PaperBroker(ExchangeAdapter):
    def __init__(
        self,
        rules: dict[str, ExchangeRule],
        initial_cash: float,
        fee_rate: float,
        slippage_bps: float,
        quote_asset: str = "USDT",
    ) -> None:
        self.rules = rules
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.quote_asset = quote_asset
        self.balances: dict[str, Balance] = {quote_asset: Balance(asset=quote_asset, free=initial_cash, locked=0.0)}
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, OrderRecord] = {}
        self.event_queue: deque[dict] = deque()
        self.fills_by_order: dict[str, FillRecord] = {}

    async def get_exchange_rules(self) -> dict[str, ExchangeRule]:
        return self.rules

    async def get_account_snapshot(self) -> AccountSnapshot:
        nav = self.balances.get(self.quote_asset, Balance(self.quote_asset, 0.0)).total
        for symbol, position in self.positions.items():
            if position.is_open:
                nav += position.quantity * position.market_price
        balances = {
            asset: Balance(asset=value.asset, free=value.free, locked=value.locked)
            for asset, value in self.balances.items()
        }
        return AccountSnapshot(
            timestamp=utc_now(),
            balances=balances,
            net_asset_value=nav,
            available_quote_balance=self.balances.get(self.quote_asset, Balance(self.quote_asset, 0.0)).free,
        )

    async def get_positions(self) -> dict[str, Position]:
        return self.positions

    async def place_market_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        fill_price = reference_price * (1 + self.slippage_bps / 10_000) if request.side == Side.BUY else reference_price * (1 - self.slippage_bps / 10_000)
        return self._fill_order(request, fill_price)

    async def place_limit_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        target = request.price if request.price is not None else reference_price
        if request.side == Side.BUY and reference_price <= target:
            return self._fill_order(request, target)
        if request.side == Side.SELL and reference_price >= target:
            return self._fill_order(request, target)

        now = utc_now()
        order = OrderRecord(
            order_id=str(uuid4()),
            client_order_id=request.client_order_id,
            symbol=normalize_symbol(request.symbol),
            side=request.side,
            order_type=OrderType.LIMIT,
            status=OrderStatus.NEW,
            quantity=request.quantity,
            price=request.price,
            filled_quantity=0.0,
            average_price=None,
            created_at=now,
            updated_at=now,
            mode="paper",
            reduce_only=request.reduce_only,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        self.orders[order.order_id] = order
        self.event_queue.append({"event": "orderUpdate", "order": order})
        return order

    async def cancel_order(self, symbol: str, order_id: str) -> OrderRecord:
        order = self.orders[order_id]
        order.status = OrderStatus.CANCELED
        order.updated_at = utc_now()
        self.event_queue.append({"event": "orderUpdate", "order": order})
        return order

    async def fetch_order(self, symbol: str, order_id: str) -> OrderRecord:
        return self.orders[order_id]

    async def stream_user_events(self) -> AsyncIterator[dict]:
        while True:
            if self.event_queue:
                yield self.event_queue.popleft()
            else:
                await __import__("asyncio").sleep(0.2)

    def consume_fill(self, order_id: str) -> FillRecord | None:
        return self.fills_by_order.pop(order_id, None)

    def update_mark_price(self, bar: Bar) -> list[FillRecord]:
        fills: list[FillRecord] = []
        position = self.positions.get(normalize_symbol(bar.symbol))
        if position and position.is_open:
            position.update_mark(bar.close)
            if position.stop_loss is not None and bar.low <= position.stop_loss:
                fills.append(self._close_position(position, position.stop_loss, "stop_loss"))
            elif position.take_profit is not None and bar.high >= position.take_profit:
                fills.append(self._close_position(position, position.take_profit, "take_profit"))

        for order in list(self.orders.values()):
            if order.status != OrderStatus.NEW or order.order_type != OrderType.LIMIT:
                continue
            if order.symbol != normalize_symbol(bar.symbol):
                continue
            if order.side == Side.BUY and order.price is not None and bar.low <= order.price:
                request = OrderRequest(
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    client_order_id=order.client_order_id,
                    idempotency_key=order.client_order_id,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    reduce_only=order.reduce_only,
                    reason=order.reason,
                )
                self._fill_order(request, cast(float, order.price), existing_order=order)
            elif order.side == Side.SELL and order.price is not None and bar.high >= order.price:
                request = OrderRequest(
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    client_order_id=order.client_order_id,
                    idempotency_key=order.client_order_id,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    reduce_only=order.reduce_only,
                    reason=order.reason,
                )
                self._fill_order(request, cast(float, order.price), existing_order=order)
        return fills

    def _fill_order(self, request: OrderRequest, fill_price: float, existing_order: OrderRecord | None = None) -> OrderRecord:
        now = utc_now()
        quantity = round_to_step(request.quantity, self.rules[normalize_symbol(request.symbol)].step_size)
        order = existing_order or OrderRecord(
            order_id=str(uuid4()),
            client_order_id=request.client_order_id,
            symbol=normalize_symbol(request.symbol),
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.NEW,
            quantity=quantity,
            price=request.price,
            filled_quantity=0.0,
            average_price=None,
            created_at=now,
            updated_at=now,
            mode="paper",
            reduce_only=request.reduce_only,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        order.status = OrderStatus.FILLED
        order.filled_quantity = quantity
        order.average_price = fill_price
        order.updated_at = now
        self.orders[order.order_id] = order

        fee = quantity * fill_price * self.fee_rate
        fill = FillRecord(
            fill_id=str(uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=fill_price,
            fee=fee,
            fee_asset=self.quote_asset,
            realized_pnl=0.0,
            timestamp=now,
            metadata=dict(order.metadata),
        )
        if request.side == Side.BUY:
            self._apply_buy_fill(
                order.symbol,
                quantity,
                fill_price,
                fee,
                request.stop_loss,
                request.take_profit,
                now,
                dict(order.metadata),
            )
        else:
            fill.realized_pnl = self._apply_sell_fill(order.symbol, quantity, fill_price, fee, now)
        self.fills_by_order[order.order_id] = fill
        self.event_queue.append({"event": "orderUpdate", "order": order})
        self.event_queue.append({"event": "fill", "fill": fill})
        return order

    def _apply_buy_fill(
        self,
        symbol: str,
        quantity: float,
        price: float,
        fee: float,
        stop_loss: float | None,
        take_profit: float | None,
        now: datetime,
        metadata: dict,
    ) -> None:
        cost = quantity * price + fee
        quote = self.balances.setdefault(self.quote_asset, Balance(asset=self.quote_asset, free=0.0))
        quote.free -= cost
        position = self.positions.get(symbol, Position(symbol=symbol))
        total_qty = position.quantity + quantity
        if total_qty <= 0:
            return
        position.average_price = ((position.average_price * position.quantity) + (quantity * price)) / total_qty
        position.quantity = total_qty
        position.market_price = price
        position.stop_loss = stop_loss
        position.take_profit = take_profit
        position.metadata.update(metadata)
        position.opened_at = position.opened_at or now
        position.updated_at = now
        self.positions[symbol] = position

    def _apply_sell_fill(self, symbol: str, quantity: float, price: float, fee: float, now: datetime) -> float:
        position = self.positions.setdefault(symbol, Position(symbol=symbol))
        realized = 0.0
        if quantity > 0 and position.quantity > 0:
            quantity = min(quantity, position.quantity)
            realized = (price - position.average_price) * quantity - fee
            position.quantity -= quantity
            position.realized_pnl += realized
            position.market_price = price
            position.updated_at = now
            if position.quantity <= 0:
                position.average_price = 0.0
                position.stop_loss = None
                position.take_profit = None
        proceeds = quantity * price - fee
        quote = self.balances.setdefault(self.quote_asset, Balance(asset=self.quote_asset, free=0.0))
        quote.free += proceeds
        return realized

    def _close_position(self, position: Position, exit_price: float, reason: str) -> FillRecord:
        quantity = position.quantity
        fee = quantity * exit_price * self.fee_rate
        realized = self._apply_sell_fill(position.symbol, quantity, exit_price, fee, utc_now())
        fill = FillRecord(
            fill_id=str(uuid4()),
            order_id=f"system-{uuid4()}",
            symbol=position.symbol,
            side=Side.SELL,
            quantity=quantity,
            price=exit_price,
            fee=fee,
            fee_asset=self.quote_asset,
            realized_pnl=realized,
            timestamp=utc_now(),
            metadata=dict(position.metadata),
        )
        self.event_queue.append({"event": reason, "fill": fill})
        return fill
