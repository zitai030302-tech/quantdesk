from __future__ import annotations

from data.market_overview import BinanceMarketOverviewService


def test_market_overview_filters_and_ranks_usdt_pairs() -> None:
    service = BinanceMarketOverviewService(
        rest_base_url="https://api.binance.com",
        market_data_rest_base_url="https://data-api.binance.vision",
        quote_asset="USDT",
        limit=3,
        min_quote_volume=1_000_000.0,
    )

    payload = [
        {
            "symbol": "BTCUSDT",
            "lastPrice": "100000",
            "priceChangePercent": "5.5",
            "priceChange": "5200",
            "highPrice": "101000",
            "lowPrice": "95000",
            "quoteVolume": "1200000000",
            "volume": "12000",
            "count": 100000,
        },
        {
            "symbol": "DOGEUSDT",
            "lastPrice": "0.31",
            "priceChangePercent": "18.2",
            "priceChange": "0.04",
            "highPrice": "0.33",
            "lowPrice": "0.25",
            "quoteVolume": "450000000",
            "volume": "1500000000",
            "count": 220000,
        },
        {
            "symbol": "ETHUPUSDT",
            "lastPrice": "3.1",
            "priceChangePercent": "40.0",
            "priceChange": "0.8",
            "highPrice": "3.3",
            "lowPrice": "2.0",
            "quoteVolume": "50000000",
            "volume": "12345",
            "count": 5000,
        },
        {
            "symbol": "ETHBTC",
            "lastPrice": "0.05",
            "priceChangePercent": "10.0",
            "priceChange": "0.001",
            "highPrice": "0.051",
            "lowPrice": "0.048",
            "quoteVolume": "10000000",
            "volume": "1000",
            "count": 100,
        },
        {
            "symbol": "SOLUSDT",
            "lastPrice": "210",
            "priceChangePercent": "12.8",
            "priceChange": "23",
            "highPrice": "219",
            "lowPrice": "180",
            "quoteVolume": "800000000",
            "volume": "4200000",
            "count": 180000,
        },
    ]

    rows = service._filter_and_rank(payload)

    assert [row["symbol"] for row in rows] == ["DOGEUSDT", "SOLUSDT", "BTCUSDT"]
    assert all(not row["symbol"].startswith("ETHUP") for row in rows)
    assert all(row["symbol"].endswith("USDT") for row in rows)
