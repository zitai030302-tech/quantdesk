from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from data.models import AccountSnapshot, ExchangeRule, OrderRecord, OrderRequest, Position


class ExchangeAdapter(ABC):
    @abstractmethod
    async def get_exchange_rules(self) -> dict[str, ExchangeRule]:
        raise NotImplementedError

    @abstractmethod
    async def get_account_snapshot(self) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def get_positions(self) -> dict[str, Position]:
        raise NotImplementedError

    @abstractmethod
    async def place_market_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        raise NotImplementedError

    @abstractmethod
    async def place_limit_order(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> OrderRecord:
        raise NotImplementedError

    @abstractmethod
    async def fetch_order(self, symbol: str, order_id: str) -> OrderRecord:
        raise NotImplementedError

    @abstractmethod
    async def stream_user_events(self) -> AsyncIterator[dict]:
        raise NotImplementedError
