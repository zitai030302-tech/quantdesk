from datetime import datetime, timedelta, timezone

from app.types import RiskConfig, RuntimeMode
from data.models import AccountSnapshot, Balance, Bar, ExchangeRule, FillRecord, Position, Side, Signal, SignalType
from risk.manager import RiskManager


def build_history() -> list[Bar]:
    bars: list[Bar] = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    for index in range(20):
        bars.append(
            Bar(
                symbol="BTC/USDT",
                timeframe="1m",
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index, seconds=59),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=10,
            )
        )
        price += 0.5
    return bars


def test_risk_manager_sizes_buy_signal() -> None:
    manager = RiskManager(RiskConfig(), RuntimeMode.PAPER)
    account = AccountSnapshot(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        balances={"USDT": Balance(asset="USDT", free=10000.0)},
        net_asset_value=10000.0,
        available_quote_balance=10000.0,
    )
    rule = ExchangeRule("BTCUSDT", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=10.0, base_asset="BTC", quote_asset="USDT")
    signal = Signal("ema_trend", "BTC/USDT", "1m", SignalType.BUY, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")
    decision = manager.evaluate_signal(signal, account, None, rule, build_history())
    assert decision.allowed
    assert decision.quantity > 0
    assert decision.stop_loss is not None
    assert decision.take_profit is not None


def test_risk_manager_pauses_after_loss_streak() -> None:
    manager = RiskManager(RiskConfig(max_loss_streak=3), RuntimeMode.PAPER)
    for index in range(3):
        manager.on_trade_closed(
            FillRecord(
                fill_id=str(index),
                order_id=str(index),
                symbol="BTCUSDT",
                side=Side.SELL,
                quantity=1.0,
                price=100.0,
                fee=0.1,
                fee_asset="USDT",
                realized_pnl=-10.0,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
    assert manager.risk_status().value == "paused"
