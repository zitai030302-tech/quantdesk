from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.types import ExchangeConfig, RuntimeMode
from data.market_data import BinanceMarketDataFeed, CSVReplayMarketDataFeed


def test_csv_replay_stream_skips_warmup_bars() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    csv_path = base_dir / "tests" / "fixtures" / "btcusdt_1m_sample.csv"
    feed = CSVReplayMarketDataFeed(str(csv_path))

    warmup = asyncio.run(feed.warmup("BTC/USDT", "1m", 5))
    streamed: list = []

    async def collect() -> None:
        async for bar in feed.stream_bars("BTC/USDT", "1m"):
            streamed.append(bar)
            if len(streamed) >= 3:
                break

    asyncio.run(collect())
    assert len(warmup) == 5
    assert len(streamed) == 3
    assert streamed[0].open_time > warmup[-1].open_time


def test_binance_market_data_feed_falls_back_to_csv_on_http_451() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    csv_path = base_dir / "tests" / "fixtures" / "btcusdt_1m_sample.csv"
    feed = BinanceMarketDataFeed(
        ExchangeConfig(),
        RuntimeMode.PAPER,
        fallback_csv_path=str(csv_path),
        fallback_replay_delay_sec=0.0,
        fallback_loop_forever=False,
    )

    request = httpx.Request("GET", "https://api.binance.com/api/v3/klines")
    response = httpx.Response(451, request=request)

    async def failing_request(*_args, **_kwargs):
        raise httpx.HTTPStatusError("restricted", request=request, response=response)

    feed.rest_client.request = failing_request  # type: ignore[method-assign]
    if feed.market_data_only_rest_client is not None:
        feed.market_data_only_rest_client.request = failing_request  # type: ignore[method-assign]

    warmup = asyncio.run(feed.warmup("BTC/USDT", "1m", 4))
    streamed: list = []

    async def collect() -> None:
        async for bar in feed.stream_bars("BTC/USDT", "1m"):
            streamed.append(bar)
            if len(streamed) >= 2:
                break

    asyncio.run(collect())
    assert len(warmup) == 4
    assert len(streamed) == 2
    assert streamed[0].open_time > warmup[-1].open_time
