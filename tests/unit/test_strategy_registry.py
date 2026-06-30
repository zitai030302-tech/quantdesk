from strategies.registry import build_strategy_from_config, resolve_strategy_name, strategy_public_name
from app.types import StrategyConfig, StrategyParams


def build_strategy_config() -> StrategyConfig:
    return StrategyConfig(
        active_strategy="ema_trend",
        ema_trend=StrategyParams({"fast_period": 9, "slow_period": 21, "atr_period": 14}),
        rsi_bbands_mean_reversion=StrategyParams({"rsi_period": 14, "bb_period": 20}),
    )


def test_strategy_registry_accepts_public_name_alias() -> None:
    assert resolve_strategy_name("EMATrendStrategy") == "ema_trend"
    assert strategy_public_name("ema_trend") == "EMATrendStrategy"


def test_strategy_registry_builds_strategy_from_public_name() -> None:
    config = build_strategy_config()
    strategy = build_strategy_from_config("RSIBBandsMeanReversionStrategy", "BTC/USDT", "1m", config)
    assert strategy.name == "rsi_bbands_mean_reversion"
    assert strategy.symbol == "BTC/USDT"
