from __future__ import annotations

from dataclasses import dataclass

from app.types import StrategyConfig
from strategies.base import BaseStrategy
from strategies.ema_trend import EMATrendStrategy
from strategies.rsi_bbands_mean_reversion import RSIBBandsMeanReversionStrategy


@dataclass(frozen=True, slots=True)
class StrategySpec:
    internal_name: str
    public_name: str
    description: str
    aliases: tuple[str, ...]


STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec(
        internal_name="ema_trend",
        public_name="EMATrendStrategy",
        description="EMA 趋势跟随策略，适合顺势场景。",
        aliases=("ema_trend", "EMATrendStrategy", "ema-trend", "ema"),
    ),
    StrategySpec(
        internal_name="rsi_bbands_mean_reversion",
        public_name="RSIBBandsMeanReversionStrategy",
        description="RSI + 布林带均值回归策略，适合震荡回归场景。",
        aliases=(
            "rsi_bbands_mean_reversion",
            "RSIBBandsMeanReversionStrategy",
            "rsi-bbands",
            "rsi_bbands",
            "bbands",
        ),
    ),
)


def list_strategy_specs() -> list[StrategySpec]:
    return list(STRATEGY_SPECS)


def resolve_strategy_name(value: str | None) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return "ema_trend"
    lowered = candidate.lower()
    for spec in STRATEGY_SPECS:
        for alias in spec.aliases:
            if lowered == alias.lower():
                return spec.internal_name
    supported = ", ".join(spec.public_name for spec in STRATEGY_SPECS)
    raise ValueError(f"不支持的策略名称：{candidate}。可用策略：{supported}")


def strategy_public_name(value: str | None) -> str:
    internal = resolve_strategy_name(value)
    for spec in STRATEGY_SPECS:
        if spec.internal_name == internal:
            return spec.public_name
    return internal


def build_strategy_from_config(
    strategy_name: str | None,
    symbol: str,
    timeframe: str,
    strategy_config: StrategyConfig,
) -> BaseStrategy:
    internal = resolve_strategy_name(strategy_name or strategy_config.active_strategy)
    if internal == "ema_trend":
        return EMATrendStrategy(
            name=internal,
            symbol=symbol,
            timeframe=timeframe,
            params=strategy_config.ema_trend.values,
        )
    if internal == "rsi_bbands_mean_reversion":
        return RSIBBandsMeanReversionStrategy(
            name=internal,
            symbol=symbol,
            timeframe=timeframe,
            params=strategy_config.rsi_bbands_mean_reversion.values,
        )
    raise ValueError(f"不支持的策略名称：{internal}")
