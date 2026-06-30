from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx

from app.types import ExchangeConfig, RuntimeMode, normalize_symbol
from data.csv_loader import load_ohlcv_csv
from data.models import Bar
from data.rest_client import BinanceRestClient
from data.websocket_client import ReconnectingWebSocketClient


LOGGER = logging.getLogger("data.market_data")


def _dt_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


class MarketDataFeed(ABC):
    @abstractmethod
    async def warmup(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        raise NotImplementedError

    @abstractmethod
    async def stream_bars(self, symbol: str, timeframe: str) -> AsyncIterator[Bar]:
        raise NotImplementedError


class CSVReplayMarketDataFeed(MarketDataFeed):
    def __init__(self, csv_path: str, replay_delay_sec: float = 0.0, loop_forever: bool = False) -> None:
        self.csv_path = csv_path
        self.replay_delay_sec = replay_delay_sec
        self.loop_forever = loop_forever
        self._cache: dict[tuple[str, str], list[Bar]] = {}
        self._stream_offsets: dict[tuple[str, str], int] = {}

    def _bars_for(self, symbol: str, timeframe: str) -> list[Bar]:
        key = (normalize_symbol(symbol), timeframe)
        if key not in self._cache:
            self._cache[key] = load_ohlcv_csv(self.csv_path, symbol, timeframe)
        return self._cache[key]

    async def warmup(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        bars = self._bars_for(symbol, timeframe)
        count = min(limit, len(bars))
        self._stream_offsets[(normalize_symbol(symbol), timeframe)] = count
        return bars[:count]

    async def stream_bars(self, symbol: str, timeframe: str) -> AsyncIterator[Bar]:
        bars = self._bars_for(symbol, timeframe)
        key = (normalize_symbol(symbol), timeframe)
        start_offset = self._stream_offsets.get(key, 0)
        first_cycle = True
        while True:
            cycle_start = start_offset if first_cycle else 0
            for bar in bars[cycle_start:]:
                if self.replay_delay_sec > 0:
                    await asyncio.sleep(self.replay_delay_sec)
                yield bar
            if not self.loop_forever or not bars:
                break
            first_cycle = False


class BinanceMarketDataFeed(MarketDataFeed):
    def __init__(
        self,
        exchange_config: ExchangeConfig,
        mode: RuntimeMode,
        fallback_csv_path: str | None = None,
        fallback_replay_delay_sec: float = 0.5,
        fallback_loop_forever: bool = True,
    ) -> None:
        base_url = (
            exchange_config.testnet_rest_base_url if mode == RuntimeMode.TESTNET else exchange_config.rest_base_url
        )
        self.rest_client = BinanceRestClient(base_url=base_url)
        self.market_data_only_rest_client = (
            BinanceRestClient(base_url=exchange_config.market_data_rest_base_url)
            if mode != RuntimeMode.TESTNET and exchange_config.market_data_rest_base_url
            else None
        )
        self.exchange_config = exchange_config
        self.mode = mode
        self.fallback_feed = (
            CSVReplayMarketDataFeed(
                fallback_csv_path,
                replay_delay_sec=fallback_replay_delay_sec,
                loop_forever=fallback_loop_forever,
            )
            if fallback_csv_path
            else None
        )
        self._using_market_data_only = False
        self._using_fallback = False

    def _activate_market_data_only(self, reason: Exception) -> None:
        self._using_market_data_only = True
        LOGGER.warning(
            "主 Binance 行情端点不可用，切换到官方只读行情端点 | 模式=%s | 原因=%s",
            self.mode.value,
            reason,
        )

    def _activate_fallback(self, reason: Exception) -> None:
        self._using_fallback = True
        LOGGER.warning(
            "Binance 行情暂时不可用，回退到本地 CSV 回放 | 模式=%s | 原因=%s",
            self.mode.value,
            reason,
        )

    async def warmup(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        if self._using_fallback and self.fallback_feed:
            return await self.fallback_feed.warmup(symbol, timeframe, limit)
        try:
            active_client = self.market_data_only_rest_client if self._using_market_data_only else self.rest_client
            payload = await active_client.request(
                "GET",
                "/api/v3/klines",
                params={"symbol": normalize_symbol(symbol), "interval": timeframe, "limit": limit},
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if not self._using_market_data_only and self.market_data_only_rest_client is not None:
                self._activate_market_data_only(exc)
                return await self.warmup(symbol, timeframe, limit)
            if self.fallback_feed is None:
                raise
            self._activate_fallback(exc)
            return await self.fallback_feed.warmup(symbol, timeframe, limit)
        return [self._parse_rest_kline(symbol, timeframe, item) for item in payload]

    def _stream_url(self, symbol: str, timeframe: str) -> str:
        base = (
            self.exchange_config.testnet_ws_base_url
            if self.mode == RuntimeMode.TESTNET
            else (self.exchange_config.market_data_ws_base_url if self._using_market_data_only else self.exchange_config.ws_base_url)
        )
        stream = f"{normalize_symbol(symbol).lower()}@kline_{timeframe}"
        return f"{base.rstrip('/')}/{stream}"

    async def stream_bars(self, symbol: str, timeframe: str) -> AsyncIterator[Bar]:
        if self._using_fallback and self.fallback_feed:
            async for bar in self.fallback_feed.stream_bars(symbol, timeframe):
                yield bar
            return
        client = ReconnectingWebSocketClient(self._stream_url(symbol, timeframe))
        async for payload in client.stream():
            data = payload.get("k") or payload.get("data", {}).get("k")
            if not data:
                continue
            yield Bar(
                symbol=symbol,
                timeframe=timeframe,
                open_time=_dt_from_ms(int(data["t"])),
                close_time=_dt_from_ms(int(data["T"])),
                open=float(data["o"]),
                high=float(data["h"]),
                low=float(data["l"]),
                close=float(data["c"]),
                volume=float(data["v"]),
                quote_volume=float(data.get("q", 0.0)),
                trades=int(data.get("n", 0)),
                is_closed=bool(data["x"]),
                source="ws",
            )

    @staticmethod
    def _parse_rest_kline(symbol: str, timeframe: str, item: list) -> Bar:
        return Bar(
            symbol=symbol,
            timeframe=timeframe,
            open_time=_dt_from_ms(int(item[0])),
            close_time=_dt_from_ms(int(item[6])),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            quote_volume=float(item[7]),
            trades=int(item[8]),
            is_closed=True,
            source="rest",
        )
