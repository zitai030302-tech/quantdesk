from strategies.indicators import atr, bollinger_bands, ema, rsi
from data.models import Bar
from datetime import datetime, timedelta, timezone


def build_bars() -> list[Bar]:
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
        price += 1
    return bars


def test_ema_returns_expected_shape() -> None:
    values = [1, 2, 3, 4, 5, 6]
    result = ema(values, 3)
    assert result[:2] == [None, None]
    assert result[-1] is not None
    assert round(result[-1] or 0.0, 4) == 5.0


def test_rsi_trending_series_is_high() -> None:
    values = list(range(1, 25))
    result = rsi(values, 14)
    assert result[-1] is not None
    assert (result[-1] or 0.0) > 70


def test_bollinger_bands_and_atr_produce_values() -> None:
    closes = [bar.close for bar in build_bars()]
    bands = bollinger_bands(closes, 5, 2.0)
    atr_values = atr(build_bars(), 5)
    assert bands[-1][0] is not None
    assert bands[-1][2] is not None
    assert atr_values[-1] is not None
