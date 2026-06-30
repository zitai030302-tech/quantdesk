from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from data.models import (
    AccountSnapshot,
    Balance,
    ExchangeRule,
    OrderRecord,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    FillRecord,
    utc_now,
)
from data.rest_client import BinanceRestClient
from data.websocket_client import BinanceWebSocketApiClient
from execution.adapter_base import ExchangeAdapter
from execution.filters import extract_symbol_rules
from execution.reconciliation import reconcile_orders


def _dt_from_ms(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


LOGGER = logging.getLogger("execution.binance_spot")


class BinanceSpotAdapter(ExchangeAdapter):
    def __init__(
        self,
        rest_base_url: str,
        ws_api_url: str,
        api_key: str,
        api_secret: str,
        timeout_sec: float,
        recv_window_ms: int,
        sync_interval_sec: float = 3.0,
        quote_asset: str = "USDT",
        reconnect_delay_sec: float = 2.0,
        market_data_rest_base_url: str | None = None,
        fallback_exchange_info_path: str | None = None,
        read_only: bool = False,
        planning_quote_balance: float = 10000.0,
        mode_label: str = "testnet",
    ) -> None:
        self.rest_client = BinanceRestClient(
            base_url=rest_base_url,
            api_key=api_key,
            api_secret=api_secret,
            timeout_sec=timeout_sec,
            recv_window_ms=recv_window_ms,
        )
        self.market_data_only_rest_client = (
            BinanceRestClient(
                base_url=market_data_rest_base_url,
                timeout_sec=timeout_sec,
                recv_window_ms=recv_window_ms,
            )
            if market_data_rest_base_url
            else None
        )
        self.ws_api_url = ws_api_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window_ms = recv_window_ms
        self.sync_interval_sec = sync_interval_sec
        self.quote_asset = quote_asset
        self.reconnect_delay_sec = reconnect_delay_sec
        self.fallback_exchange_info_path = Path(fallback_exchange_info_path).resolve() if fallback_exchange_info_path else None
        self.read_only = read_only
        self.planning_quote_balance = planning_quote_balance
        self.mode_label = mode_label
        self._cached_rules: dict[str, ExchangeRule] = {}
        self._balances: dict[str, Balance] = {}
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, OrderRecord] = {}
        self._account_snapshot: AccountSnapshot | None = None

    async def get_exchange_rules(self) -> dict[str, ExchangeRule]:
        if self._cached_rules:
            return self._cached_rules
        try:
            payload = await self.rest_client.request("GET", "/api/v3/exchangeInfo")
        except (httpx.HTTPStatusError, httpx.RequestError) as primary_exc:
            try:
                if self.market_data_only_rest_client is None:
                    raise primary_exc
                payload = await self.market_data_only_rest_client.request("GET", "/api/v3/exchangeInfo")
            except (httpx.HTTPStatusError, httpx.RequestError):
                if self.fallback_exchange_info_path is None or not self.fallback_exchange_info_path.exists():
                    raise
                LOGGER.warning(
                    "Binance 网络端点暂时无法获取 exchangeInfo，改用本地回退文件：%s",
                    self.fallback_exchange_info_path,
                )
                payload = json.loads(self.fallback_exchange_info_path.read_text(encoding="utf-8"))
        self._cached_rules = extract_symbol_rules(payload)
        return self._cached_rules

    async def get_account_snapshot(self) -> AccountSnapshot:
        if self._account_snapshot is None:
            if self._credentials_available():
                await self._sync_from_rest()
            else:
                self._initialize_reference_account()
        assert self._account_snapshot is not None
        return self._account_snapshot

    async def _fetch_account_snapshot_rest(self) -> AccountSnapshot:
        payload = await self.rest_client.request("GET", "/api/v3/account", signed=True)
        balances = {
            item["asset"]: Balance(asset=item["asset"], free=float(item["free"]), locked=float(item["locked"]))
            for item in payload.get("balances", [])
            if float(item["free"]) > 0 or float(item["locked"]) > 0
        }
        timestamp = _dt_from_ms(payload.get("updateTime", 0) or int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        self._balances = balances
        self._sync_positions_from_balances()
        self._account_snapshot = self._build_account_snapshot(timestamp)
        return self._account_snapshot

    async def get_positions(self) -> dict[str, Position]:
        if self._account_snapshot is None:
            if self._credentials_available():
                await self._sync_from_rest()
            else:
                self._initialize_reference_account()
        return self._positions

    async def place_market_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        if self.read_only:
            raise RuntimeError("只读适配器不允许提交订单")
        params = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": "MARKET",
            "quantity": request.quantity,
            "newClientOrderId": request.client_order_id,
        }
        payload = await self.rest_client.request("POST", "/api/v3/order", params=params, signed=True)
        order = self._parse_order(payload, mode=self.mode_label)
        order.reason = request.reason
        order.stop_loss = request.stop_loss
        order.take_profit = request.take_profit
        order.reduce_only = request.reduce_only
        order.metadata = dict(request.metadata)
        self._orders[order.order_id] = order
        return order

    async def place_limit_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        if self.read_only:
            raise RuntimeError("只读适配器不允许提交订单")
        params = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": request.quantity,
            "price": request.price,
            "newClientOrderId": request.client_order_id,
        }
        payload = await self.rest_client.request("POST", "/api/v3/order", params=params, signed=True)
        order = self._parse_order(payload, mode=self.mode_label)
        order.reason = request.reason
        order.stop_loss = request.stop_loss
        order.take_profit = request.take_profit
        order.reduce_only = request.reduce_only
        order.metadata = dict(request.metadata)
        self._orders[order.order_id] = order
        return order

    async def cancel_order(self, symbol: str, order_id: str) -> OrderRecord:
        if self.read_only:
            raise RuntimeError("只读适配器不允许撤单")
        payload = await self.rest_client.request(
            "DELETE",
            "/api/v3/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        order = self._parse_order(payload, mode=self.mode_label)
        self._orders[order.order_id] = order
        return order

    async def fetch_order(self, symbol: str, order_id: str) -> OrderRecord:
        if not self._credentials_available():
            raise RuntimeError("查询远端订单前需要提供已认证的 Binance API 凭证")
        payload = await self.rest_client.request(
            "GET",
            "/api/v3/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return self._parse_order(payload, mode=self.mode_label)

    async def stream_user_events(self) -> AsyncIterator[dict]:
        if not self._credentials_available():
            if False:
                yield {}
            return
        while True:
            client = BinanceWebSocketApiClient(
                url=self.ws_api_url,
                api_key=self.api_key,
                api_secret=self.api_secret,
                recv_window_ms=self.recv_window_ms,
                reconnect_delay_sec=self.reconnect_delay_sec,
            )
            try:
                yield {"event": "connectionEvent", "channel": "user_stream", "state": "bootstrap", "message": "正在通过 REST 同步账户状态"}
                await self._sync_from_rest()
                yield {"event": "accountSnapshot", "account": await self.get_account_snapshot(), "source": "rest_bootstrap"}

                yield {"event": "connectionEvent", "channel": "user_stream", "state": "connecting", "message": "正在连接 WebSocket API 会话"}
                await client.connect()
                yield {"event": "connectionEvent", "channel": "user_stream", "state": "connected", "message": "WebSocket API 会话已连接"}
                response = await client.request("userDataStream.subscribe.signature", signed=True)
                yield {
                    "event": "subscriptionStarted",
                    "subscription_id": response.get("result", {}).get("subscriptionId"),
                }

                loop = asyncio.get_running_loop()
                next_reconcile = loop.time() + self.sync_interval_sec
                while True:
                    timeout = max(0.1, next_reconcile - loop.time())
                    try:
                        payload = await asyncio.wait_for(client.next_event(), timeout=timeout)
                    except TimeoutError:
                        for event in await self._reconcile_state():
                            yield event
                        next_reconcile = loop.time() + self.sync_interval_sec
                        continue

                    for event in self._translate_user_stream_payload(payload):
                        yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network dependent
                LOGGER.warning("账户流发生异常：%s", exc)
                yield {
                    "event": "connectionEvent",
                    "channel": "user_stream",
                    "state": "reconnecting",
                    "message": f"账户流将自动重连：{exc}",
                }
                yield {"event": "streamError", "message": str(exc)}
                await asyncio.sleep(self.reconnect_delay_sec)
            finally:
                await client.close()

    async def _sync_from_rest(self) -> tuple[AccountSnapshot, dict[str, OrderRecord]]:
        account = await self._fetch_account_snapshot_rest()
        open_orders = await self._fetch_open_orders_rest()
        self._orders.update(open_orders)
        return account, open_orders

    async def _fetch_open_orders_rest(self) -> dict[str, OrderRecord]:
        payload = await self.rest_client.request("GET", "/api/v3/openOrders", signed=True)
        remote_orders: dict[str, OrderRecord] = {}
        for item in payload:
            order = self._parse_order(item, mode=self.mode_label)
            order = self._merge_local_order_context(order)
            remote_orders[order.order_id] = order
        return remote_orders

    async def _reconcile_state(self) -> list[dict]:
        before_balances = {
            asset: (balance.free, balance.locked)
            for asset, balance in self._balances.items()
        }
        local_open_orders = {
            order_id: order
            for order_id, order in self._orders.items()
            if order.status in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}
        }
        account, remote_open_orders = await self._sync_from_rest()
        mismatches = reconcile_orders(local_open_orders, remote_open_orders)
        after_balances = {
            asset: (balance.free, balance.locked)
            for asset, balance in self._balances.items()
        }
        events: list[dict] = []
        if before_balances != after_balances:
            events.append({"event": "accountSnapshot", "account": account, "source": "rest_reconcile"})
        if mismatches:
            events.append(
                {
                    "event": "syncWarning",
                    "message": "对账时发现订单或账户状态不一致",
                    "details": {"mismatches": mismatches},
                }
            )
        return events

    def _translate_user_stream_payload(self, payload: dict) -> list[dict]:
        event = payload.get("event") or {}
        event_type = event.get("e")
        if event_type == "outboundAccountPosition":
            self._apply_account_position_event(event)
            return [{"event": "accountSnapshot", "account": self._account_snapshot, "source": "user_stream"}]
        if event_type == "balanceUpdate":
            self._apply_balance_delta_event(event)
            return [{"event": "accountSnapshot", "account": self._account_snapshot, "source": "user_stream"}]
        if event_type == "executionReport":
            order, fill = self._apply_execution_report_event(event)
            translated = [{"event": "orderUpdate", "order": order}]
            if fill:
                translated.append({"event": "fill", "fill": fill})
                translated.append({"event": "accountSnapshot", "account": self._account_snapshot, "source": "user_stream"})
            return translated
        if event_type == "eventStreamTerminated":
            return [{"event": "streamTerminated", "message": "交易所已终止账户数据流"}]
        if event_type == "externalLockUpdate":
            return [{"event": "externalLockUpdate", "payload": event}]
        if event_type == "clientError":
            return [{"event": "streamError", "message": event.get("message", "客户端错误")}]
        if payload.get("event", {}).get("type") == "serverShutdown":
            return [{"event": "streamTerminated", "message": "服务器已关闭"}]
        return []

    def _apply_account_position_event(self, payload: dict) -> None:
        for item in payload.get("B", []):
            self._balances[item["a"]] = Balance(
                asset=item["a"],
                free=float(item["f"]),
                locked=float(item["l"]),
            )
        self._sync_positions_from_balances()
        self._account_snapshot = self._build_account_snapshot(_dt_from_ms(payload.get("E", int(utc_now().timestamp() * 1000))))

    def _apply_balance_delta_event(self, payload: dict) -> None:
        asset = payload.get("a", "")
        delta = float(payload.get("d", 0.0))
        balance = self._balances.get(asset, Balance(asset=asset, free=0.0, locked=0.0))
        balance.free += delta
        self._balances[asset] = balance
        self._sync_positions_from_balances()
        self._account_snapshot = self._build_account_snapshot(_dt_from_ms(payload.get("E", int(utc_now().timestamp() * 1000))))

    def _apply_execution_report_event(self, payload: dict) -> tuple[OrderRecord, FillRecord | None]:
        order = self._parse_order(
            {
                "orderId": payload.get("i"),
                "clientOrderId": payload.get("c"),
                "symbol": payload.get("s"),
                "side": payload.get("S"),
                "type": payload.get("o"),
                "status": payload.get("X"),
                "origQty": payload.get("q"),
                "price": payload.get("p"),
                "executedQty": payload.get("z"),
                "cummulativeQuoteQty": payload.get("Z"),
                "transactTime": payload.get("T"),
                "workingTime": payload.get("W", payload.get("E")),
                "time": payload.get("O", payload.get("E")),
            },
            mode=self.mode_label,
        )
        order = self._merge_local_order_context(order)
        self._orders[order.order_id] = order

        last_qty = float(payload.get("l", 0.0))
        last_price = float(payload.get("L", 0.0))
        if last_qty <= 0 or last_price <= 0:
            return order, None

        fee = float(payload.get("n", 0.0))
        fee_asset = payload.get("N") or self.quote_asset
        fill = FillRecord(
            fill_id=str(payload.get("I") or payload.get("t") or uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=last_qty,
            price=last_price,
            fee=fee,
            fee_asset=fee_asset,
            realized_pnl=0.0,
            timestamp=_dt_from_ms(payload.get("T", payload.get("E", int(utc_now().timestamp() * 1000)))),
            metadata=dict(order.metadata),
        )
        if order.side == Side.BUY:
            self._apply_buy_fill(order.symbol, last_qty, last_price, fee)
        else:
            fill.realized_pnl = self._apply_sell_fill(order.symbol, last_qty, last_price, fee)
        self._account_snapshot = self._build_account_snapshot(fill.timestamp)
        return order, fill

    def _apply_buy_fill(self, symbol: str, quantity: float, price: float, fee: float) -> None:
        rule = self._cached_rules.get(symbol)
        base_asset = rule.base_asset if rule else symbol[:-4]
        quote_asset = rule.quote_asset if rule else self.quote_asset
        quote_balance = self._balances.get(quote_asset, Balance(asset=quote_asset, free=0.0))
        quote_balance.free -= (quantity * price) + fee
        self._balances[quote_asset] = quote_balance

        base_balance = self._balances.get(base_asset, Balance(asset=base_asset, free=0.0))
        base_balance.free += quantity
        self._balances[base_asset] = base_balance

        position = self._positions.get(symbol, Position(symbol=symbol))
        total_qty = position.quantity + quantity
        if total_qty > 0:
            position.average_price = ((position.average_price * position.quantity) + (quantity * price)) / total_qty
        position.quantity = total_qty
        position.market_price = price
        position.opened_at = position.opened_at or utc_now()
        position.updated_at = utc_now()
        self._positions[symbol] = position

    def _apply_sell_fill(self, symbol: str, quantity: float, price: float, fee: float) -> float:
        rule = self._cached_rules.get(symbol)
        base_asset = rule.base_asset if rule else symbol[:-4]
        quote_asset = rule.quote_asset if rule else self.quote_asset
        base_balance = self._balances.get(base_asset, Balance(asset=base_asset, free=0.0))
        base_balance.free = max(0.0, base_balance.free - quantity)
        self._balances[base_asset] = base_balance

        quote_balance = self._balances.get(quote_asset, Balance(asset=quote_asset, free=0.0))
        quote_balance.free += (quantity * price) - fee
        self._balances[quote_asset] = quote_balance

        position = self._positions.get(symbol, Position(symbol=symbol))
        sell_qty = min(quantity, position.quantity)
        realized = ((price - position.average_price) * sell_qty) - fee if position.average_price > 0 else -fee
        position.quantity = max(0.0, position.quantity - sell_qty)
        position.market_price = price
        position.realized_pnl += realized
        position.updated_at = utc_now()
        if position.quantity <= 0:
            position.average_price = 0.0
        self._positions[symbol] = position
        return realized

    def _sync_positions_from_balances(self) -> None:
        tracked_symbols = set()
        for asset, balance in self._balances.items():
            if asset == self.quote_asset or balance.total <= 0:
                continue
            symbol = f"{asset}{self.quote_asset}"
            tracked_symbols.add(symbol)
            position = self._positions.get(symbol, Position(symbol=symbol))
            position.quantity = balance.total
            if position.market_price <= 0:
                position.market_price = position.average_price
            position.updated_at = utc_now()
            self._positions[symbol] = position
        for symbol, position in list(self._positions.items()):
            if symbol not in tracked_symbols:
                position.quantity = 0.0
                position.updated_at = utc_now()

    def _credentials_available(self) -> bool:
        invalid_tokens = {"your_testnet_api_key", "your_testnet_api_secret", "your_mainnet_api_key", "your_mainnet_api_secret"}
        return bool(
            self.api_key
            and self.api_secret
            and self.api_key not in invalid_tokens
            and self.api_secret not in invalid_tokens
        )

    def _initialize_reference_account(self) -> None:
        if not self._balances:
            self._balances = {
                self.quote_asset: Balance(
                    asset=self.quote_asset,
                    free=self.planning_quote_balance,
                    locked=0.0,
                )
            }
        self._account_snapshot = self._build_account_snapshot(utc_now())

    def _build_account_snapshot(self, timestamp: datetime) -> AccountSnapshot:
        available_quote = self._balances.get(self.quote_asset, Balance(asset=self.quote_asset, free=0.0)).free
        net_value = self._balances.get(self.quote_asset, Balance(asset=self.quote_asset, free=0.0)).total
        for symbol, position in self._positions.items():
            if position.quantity <= 0:
                continue
            reference_price = position.market_price or position.average_price
            net_value += position.quantity * reference_price
        return AccountSnapshot(
            timestamp=timestamp,
            balances={asset: Balance(asset=bal.asset, free=bal.free, locked=bal.locked) for asset, bal in self._balances.items()},
            net_asset_value=net_value,
            available_quote_balance=available_quote,
        )

    def _merge_local_order_context(self, order: OrderRecord) -> OrderRecord:
        previous = self._orders.get(order.order_id)
        if not previous:
            previous = next(
                (
                    existing
                    for existing in self._orders.values()
                    if existing.client_order_id == order.client_order_id and existing.client_order_id
                ),
                None,
            )
        if previous:
            order.reason = previous.reason
            order.stop_loss = previous.stop_loss
            order.take_profit = previous.take_profit
            order.reduce_only = previous.reduce_only
            order.metadata = dict(previous.metadata)
        return order

    @staticmethod
    def _parse_order(payload: dict, mode: str) -> OrderRecord:
        status_value = payload.get("status", "NEW")
        try:
            status = OrderStatus(status_value)
        except ValueError:
            status = OrderStatus.NEW
        return OrderRecord(
            order_id=str(payload.get("orderId", uuid4())),
            client_order_id=payload.get("clientOrderId", ""),
            symbol=payload.get("symbol", ""),
            side=Side(payload.get("side", "BUY")),
            order_type=OrderType(payload.get("type", "MARKET")),
            status=status,
            quantity=float(payload.get("origQty", 0.0)),
            price=float(payload["price"]) if payload.get("price") not in {None, ""} else None,
            filled_quantity=float(payload.get("executedQty", 0.0)),
            average_price=float(payload["cummulativeQuoteQty"]) / float(payload["executedQty"])
            if float(payload.get("executedQty", 0.0) or 0.0) > 0
            else None,
            created_at=_dt_from_ms(payload.get("transactTime", payload.get("time", int(datetime.now(tz=timezone.utc).timestamp() * 1000)))),
            updated_at=_dt_from_ms(payload.get("updateTime", payload.get("workingTime", payload.get("transactTime", int(datetime.now(tz=timezone.utc).timestamp() * 1000))))),
            mode=mode,
            reduce_only=False,
            reason="远端订单",
        )
