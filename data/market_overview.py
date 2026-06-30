from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from data.models import utc_now
from data.rest_client import BinanceRestClient


LOGGER = logging.getLogger("data.market_overview")


class BinanceMarketOverviewService:
    def __init__(
        self,
        rest_base_url: str,
        market_data_rest_base_url: str | None = None,
        quote_asset: str = "USDT",
        limit: int = 24,
        min_quote_volume: float = 2_000_000.0,
        refresh_interval_sec: float = 20.0,
    ) -> None:
        self.primary_client = BinanceRestClient(base_url=rest_base_url)
        self.market_data_only_client = (
            BinanceRestClient(base_url=market_data_rest_base_url)
            if market_data_rest_base_url and market_data_rest_base_url.rstrip("/") != rest_base_url.rstrip("/")
            else None
        )
        self.quote_asset = quote_asset.upper()
        self.limit = limit
        self.min_quote_volume = min_quote_volume
        self.refresh_interval = timedelta(seconds=refresh_interval_sec)
        self._updated_at: datetime | None = None
        self._cache: list[dict] = []
        self._universe_cache: list[dict] = []
        self._source = "uninitialized"

    async def top_gainers(self, force: bool = False) -> list[dict]:
        if not force and self._updated_at and utc_now() - self._updated_at < self.refresh_interval and self._cache:
            return list(self._cache)

        payload = await self._fetch_ticker_payload()
        rows = self._filter_and_rank(payload)
        self._universe_cache = list(rows)
        self._cache = rows[: self.limit]
        self._updated_at = utc_now()
        return list(self._cache)

    def snapshot(self) -> dict[str, object]:
        gainers = list(self._universe_cache[: self.limit])
        losers = sorted(
            self._universe_cache,
            key=lambda row: (
                float(row["price_change_percent"]),
                float(row["quote_volume"]),
            ),
        )[: self.limit]
        volume = sorted(
            self._universe_cache,
            key=lambda row: (
                float(row["quote_volume"]),
                float(row["trade_count"]),
            ),
            reverse=True,
        )[: self.limit]
        positive_count = sum(1 for row in self._universe_cache if float(row["price_change_percent"]) > 0)
        negative_count = sum(1 for row in self._universe_cache if float(row["price_change_percent"]) < 0)
        average_change = (
            sum(float(row["price_change_percent"]) for row in self._universe_cache) / len(self._universe_cache)
            if self._universe_cache
            else 0.0
        )
        return {
            "updated_at": self._updated_at.isoformat() if self._updated_at else None,
            "source": self._source,
            "rows": gainers,
            "sections": {
                "gainers": gainers,
                "losers": losers,
                "volume": volume,
            },
            "stats": {
                "tracked_pairs": len(self._universe_cache),
                "positive_pairs": positive_count,
                "negative_pairs": negative_count,
                "average_change_percent": average_change,
            },
        }

    async def _fetch_ticker_payload(self) -> list[dict]:
        errors: list[Exception] = []
        clients = [("primary", self.primary_client)]
        if self.market_data_only_client is not None:
            clients.append(("market_data_only", self.market_data_only_client))
        for source, client in clients:
            try:
                payload = await client.request("GET", "/api/v3/ticker/24hr")
                self._source = source
                return payload
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                errors.append(exc)
                LOGGER.warning("获取 24h 涨幅榜失败，尝试下一个端点 | source=%s | error=%s", source, exc)
        if self._universe_cache:
            LOGGER.warning("24h 涨幅榜刷新失败，继续使用上一份缓存")
            return list(self._universe_cache)
        raise RuntimeError(f"无法获取 24h 行情榜单：{errors[-1]}") from errors[-1]

    def _filter_and_rank(self, payload: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for item in payload:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol.endswith(self.quote_asset):
                continue
            base_asset = symbol[: -len(self.quote_asset)]
            if not base_asset or self._looks_like_leveraged_token(base_asset):
                continue
            quote_volume = float(item.get("quoteVolume", 0.0) or 0.0)
            if quote_volume < self.min_quote_volume:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "display_symbol": f"{base_asset}/{self.quote_asset}",
                    "base_asset": base_asset,
                    "last_price": float(item.get("lastPrice", 0.0) or 0.0),
                    "price_change_percent": float(item.get("priceChangePercent", 0.0) or 0.0),
                    "price_change": float(item.get("priceChange", 0.0) or 0.0),
                    "high_price": float(item.get("highPrice", 0.0) or 0.0),
                    "low_price": float(item.get("lowPrice", 0.0) or 0.0),
                    "quote_volume": quote_volume,
                    "volume": float(item.get("volume", 0.0) or 0.0),
                    "trade_count": int(item.get("count", 0) or 0),
                }
            )
        rows.sort(
            key=lambda row: (
                float(row["price_change_percent"]),
                float(row["quote_volume"]),
                int(row["trade_count"]),
            ),
            reverse=True,
        )
        return rows

    @staticmethod
    def _looks_like_leveraged_token(base_asset: str) -> bool:
        leveraged_suffixes = ("UP", "DOWN", "BULL", "BEAR")
        return any(base_asset.endswith(suffix) for suffix in leveraged_suffixes)
