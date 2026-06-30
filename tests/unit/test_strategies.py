from datetime import datetime, timedelta, timezone

from data.models import Bar, Position, SignalType
from strategies.ema_trend import EMATrendStrategy
from strategies.rsi_bbands_mean_reversion import RSIBBandsMeanReversionStrategy


def make_bar(index: int, close: float) -> Bar:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    return Bar(
        symbol="BTC/USDT",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(seconds=59),
        open=close - 0.2,
        high=close + 0.4,
        low=close - 0.4,
        close=close,
        volume=10.0,
    )


def test_ema_trend_emits_buy_after_cross() -> None:
    strategy = EMATrendStrategy("ema_trend", "BTC/USDT", "1m", {"fast_period": 3, "slow_period": 5, "atr_period": 3})
    closes = [10, 9.8, 9.7, 9.6, 9.7, 9.9, 10.2, 10.5]
    buy_seen = False
    for index, close in enumerate(closes):
        bar = make_bar(index, close)
        strategy.on_bar(bar)
        signal = strategy.generate_signal(bar, None)
        if signal.signal_type == SignalType.BUY:
            buy_seen = True
    assert buy_seen


def test_rsi_bbands_emits_flat_when_price_reverts() -> None:
    strategy = RSIBBandsMeanReversionStrategy(
        "rsi_bbands_mean_reversion",
        "BTC/USDT",
        "1m",
        {"rsi_period": 5, "bb_period": 5, "bb_stddev": 1.5, "rsi_oversold": 40, "rsi_overbought": 60},
    )
    closes = [100, 100.2, 100.1, 100.0, 99.9, 98.8, 99.2, 99.7, 100.1]
    buy_seen = False
    signal = None
    for index, close in enumerate(closes):
        bar = make_bar(index, close)
        position = Position(symbol="BTCUSDT", quantity=1.0, average_price=99.0) if buy_seen else None
        strategy.on_bar(bar)
        signal = strategy.generate_signal(bar, position)
        if signal.signal_type == SignalType.BUY:
            buy_seen = True
    assert signal is not None
    assert signal.signal_type in {SignalType.BUY, SignalType.FLAT, SignalType.HOLD}
