import math

import pytest

from backtest.metrics import periods_per_year, sharpe_ratio


def test_hourly_sharpe_uses_hourly_observations():
    returns = [.001, -.002, .003, .0005]
    hourly = sharpe_ratio(returns, periods_per_year("1h"))
    minute = sharpe_ratio(returns, periods_per_year("1m"))
    assert periods_per_year("1h") == 8760
    assert minute / hourly == pytest.approx(math.sqrt(60))


@pytest.mark.parametrize("timeframe", ["0m", "1M", "-5m", "foo"])
def test_nonfixed_or_invalid_intervals_rejected(timeframe):
    with pytest.raises(ValueError):
        periods_per_year(timeframe)
