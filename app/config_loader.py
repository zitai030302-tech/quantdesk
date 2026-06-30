from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

try:
    import yaml
except ImportError:  # pragma: no cover - depends on environment
    yaml = None

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - depends on environment
    def dotenv_values(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

from app.types import (
    AlertsConfig,
    AppConfig,
    BacktestConfig,
    DashboardConfig,
    ExecutionConfig,
    ExchangeConfig,
    RiskConfig,
    RuntimeMode,
    StorageConfig,
    StrategyConfig,
    StrategyParams,
    SystemConfig,
)

T = TypeVar("T")


def _build_dataclass(cls: type[T], values: dict[str, Any] | None) -> T:
    values = values or {}
    kwargs: dict[str, Any] = {}
    for item in fields(cls):
        if item.name not in values:
            continue
        raw = values[item.name]
        if item.type is RuntimeMode:
            kwargs[item.name] = RuntimeMode(raw)
        elif item.type in {DashboardConfig, AlertsConfig, StrategyParams}:
            kwargs[item.name] = item.type(**raw)
        else:
            kwargs[item.name] = raw
    return cls(**kwargs)


def load_config(config_path: str | Path) -> SystemConfig:
    path = Path(config_path).resolve()
    base_dir = path.parent.parent
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text) or {}
    else:  # pragma: no cover - requirements already include PyYAML
        import json

        raw = json.loads(text)
    env_path = base_dir / ".env"
    env = {k: v for k, v in dotenv_values(env_path).items() if v is not None} if env_path.exists() else {}

    app_cfg = _build_dataclass(AppConfig, raw.get("app"))
    app_cfg.dashboard = _build_dataclass(DashboardConfig, (raw.get("app") or {}).get("dashboard"))
    app_cfg.alerts = _build_dataclass(AlertsConfig, (raw.get("app") or {}).get("alerts"))

    strategy_cfg = _build_dataclass(StrategyConfig, raw.get("strategy"))
    strategy_raw = raw.get("strategy") or {}
    strategy_cfg.ema_trend = StrategyParams(strategy_raw.get("ema_trend", {}))
    strategy_cfg.rsi_bbands_mean_reversion = StrategyParams(strategy_raw.get("rsi_bbands_mean_reversion", {}))

    config = SystemConfig(
        app=app_cfg,
        exchange=_build_dataclass(ExchangeConfig, raw.get("exchange")),
        strategy=strategy_cfg,
        risk=_build_dataclass(RiskConfig, raw.get("risk")),
        execution=_build_dataclass(ExecutionConfig, raw.get("execution")),
        storage=_build_dataclass(StorageConfig, raw.get("storage")),
        backtest=_build_dataclass(BacktestConfig, raw.get("backtest")),
        env=env,
    )

    config.exchange.rest_base_url = env.get("BINANCE_REST_BASE_URL", config.exchange.rest_base_url)
    config.exchange.ws_base_url = env.get("BINANCE_WS_BASE_URL", config.exchange.ws_base_url)
    config.exchange.ws_api_url = env.get("BINANCE_WS_API_URL", config.exchange.ws_api_url)
    config.exchange.market_data_rest_base_url = env.get(
        "BINANCE_MARKET_DATA_ONLY_REST_BASE_URL",
        config.exchange.market_data_rest_base_url,
    )
    config.exchange.market_data_ws_base_url = env.get(
        "BINANCE_MARKET_DATA_ONLY_WS_BASE_URL",
        config.exchange.market_data_ws_base_url,
    )
    config.exchange.testnet_rest_base_url = env.get(
        "BINANCE_TESTNET_REST_BASE_URL",
        config.exchange.testnet_rest_base_url,
    )
    config.exchange.testnet_ws_base_url = env.get(
        "BINANCE_TESTNET_WS_BASE_URL",
        config.exchange.testnet_ws_base_url,
    )
    config.exchange.testnet_ws_api_url = env.get(
        "BINANCE_TESTNET_WS_API_URL",
        config.exchange.testnet_ws_api_url,
    )
    return config
