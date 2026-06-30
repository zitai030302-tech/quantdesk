from datetime import datetime, timedelta, timezone

from data.models import Bar, ExchangeRule, OrderRequest, OrderType, Side
from execution.paper_broker import PaperBroker


def test_paper_broker_fills_market_buy_and_take_profit() -> None:
    rule = ExchangeRule("BTCUSDT", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=10.0, base_asset="BTC", quote_asset="USDT")
    broker = PaperBroker({"BTCUSDT": rule}, initial_cash=10000.0, fee_rate=0.001, slippage_bps=0)
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=0.1,
        client_order_id="cid-1",
        idempotency_key="key-1",
        stop_loss=95.0,
        take_profit=105.0,
    )
    order = __import__("asyncio").run(broker.place_market_order(request, 100.0))
    assert order.status.value == "FILLED"
    bar = Bar(
        symbol="BTC/USDT",
        timeframe="1m",
        open_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=59),
        open=100.0,
        high=106.0,
        low=99.0,
        close=105.5,
        volume=10.0,
    )
    fills = broker.update_mark_price(bar)
    assert fills
    assert fills[0].realized_pnl > 0
