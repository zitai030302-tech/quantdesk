from datetime import datetime, timezone

from data.models import AccountSnapshot, Balance, ExchangeRule, OrderRequest, OrderType, Side
from data.rest_client import build_ws_api_signed_params
from execution.validators import validate_order_request


def test_validate_order_request_blocks_small_notional() -> None:
    account = AccountSnapshot(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        balances={"USDT": Balance(asset="USDT", free=100.0)},
        net_asset_value=100.0,
        available_quote_balance=100.0,
    )
    rule = ExchangeRule("BTCUSDT", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=10.0, base_asset="BTC", quote_asset="USDT")
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=0.00001,
        client_order_id="cid",
        idempotency_key="key",
    )
    reasons = validate_order_request(request, rule, account, reference_price=100000.0, slippage_bps=10, fee_rate=0.001)
    assert reasons


def test_validate_order_request_blocks_insufficient_balance() -> None:
    account = AccountSnapshot(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        balances={"USDT": Balance(asset="USDT", free=5.0)},
        net_asset_value=5.0,
        available_quote_balance=5.0,
    )
    rule = ExchangeRule("BTCUSDT", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=10.0, base_asset="BTC", quote_asset="USDT")
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        client_order_id="cid",
        idempotency_key="key",
    )
    reasons = validate_order_request(request, rule, account, reference_price=20000.0, slippage_bps=10, fee_rate=0.001)
    assert "可用报价资产余额不足" in reasons


def test_validate_order_request_counts_fee_and_slippage_for_buy_orders() -> None:
    account = AccountSnapshot(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        balances={"USDT": Balance(asset="USDT", free=100.0)},
        net_asset_value=100.0,
        available_quote_balance=100.0,
    )
    rule = ExchangeRule("BTCUSDT", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=10.0, base_asset="BTC", quote_asset="USDT")
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=0.9995,
        client_order_id="cid",
        idempotency_key="key",
    )
    reasons = validate_order_request(
        request,
        rule,
        account,
        reference_price=100.0,
        slippage_bps=8,
        fee_rate=0.001,
    )
    assert "可用报价资产余额不足" in reasons


def test_build_ws_api_signed_params_matches_hmac_example() -> None:
    params = {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": "0.01000000",
        "price": "52000.00",
    }
    signed = build_ws_api_signed_params(
        params,
        api_key="vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",
        api_secret="NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j",
        recv_window_ms=100,
        timestamp_ms=1645423376532,
    )
    assert signed["signature"] == "aa1b5712c094bc4e57c05a1a5c1fd8d88dcd628338ea863fec7b88e59fe2db24"
