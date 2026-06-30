from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from execution.binance_spot import BinanceSpotAdapter
from data.models import OrderRequest, OrderType, Side


def test_read_only_adapter_without_credentials_uses_reference_balance() -> None:
    adapter = BinanceSpotAdapter(
        rest_base_url="https://api.binance.com",
        ws_api_url="wss://ws-api.binance.com:443/ws-api/v3",
        api_key="",
        api_secret="",
        timeout_sec=1.0,
        recv_window_ms=5000,
        read_only=True,
        planning_quote_balance=25000.0,
        mode_label="monitor",
    )

    snapshot = asyncio.run(adapter.get_account_snapshot())
    positions = asyncio.run(adapter.get_positions())

    assert snapshot.available_quote_balance == 25000.0
    assert snapshot.net_asset_value == 25000.0
    assert positions == {}


def test_read_only_adapter_rejects_order_submission() -> None:
    adapter = BinanceSpotAdapter(
        rest_base_url="https://api.binance.com",
        ws_api_url="wss://ws-api.binance.com:443/ws-api/v3",
        api_key="",
        api_secret="",
        timeout_sec=1.0,
        recv_window_ms=5000,
        read_only=True,
        planning_quote_balance=10000.0,
        mode_label="monitor",
    )
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        client_order_id="readonly-test",
        idempotency_key="readonly-test",
    )

    with pytest.raises(RuntimeError, match="只读适配器"):
        asyncio.run(adapter.place_market_order(request, reference_price=100000.0))


def test_exchange_rules_fall_back_to_local_fixture_when_network_unavailable() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    fixture_path = base_dir / "tests" / "fixtures" / "exchange_info.json"
    adapter = BinanceSpotAdapter(
        rest_base_url="https://api.binance.com",
        ws_api_url="wss://ws-api.binance.com:443/ws-api/v3",
        api_key="",
        api_secret="",
        timeout_sec=1.0,
        recv_window_ms=5000,
        market_data_rest_base_url="https://data-api.binance.vision",
        fallback_exchange_info_path=str(fixture_path),
        read_only=True,
        planning_quote_balance=10000.0,
        mode_label="monitor",
    )

    request = httpx.Request("GET", "https://api.binance.com/api/v3/exchangeInfo")

    async def failing_request(*_args, **_kwargs):
        raise httpx.RequestError("offline", request=request)

    adapter.rest_client.request = failing_request  # type: ignore[method-assign]
    assert adapter.market_data_only_rest_client is not None
    adapter.market_data_only_rest_client.request = failing_request  # type: ignore[method-assign]

    rules = asyncio.run(adapter.get_exchange_rules())
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert "BTCUSDT" in rules
    assert rules["BTCUSDT"].quote_asset == "USDT"
    assert fixture_payload["symbols"]
