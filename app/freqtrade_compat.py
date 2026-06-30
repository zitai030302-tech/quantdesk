from __future__ import annotations

import copy
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - requirements already include PyYAML
    yaml = None

from app.cli import apply_dashboard_choice
from app.config_loader import load_config
from app.types import RuntimeMode, SystemConfig, human_symbol
from strategies.registry import list_strategy_specs, resolve_strategy_name, strategy_public_name


def load_raw_freqtrade_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).resolve()
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text)
    else:  # pragma: no cover
        raw = json.loads(text)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是对象结构：{path}")
    return raw


def _default_system_config_path(config_path: Path) -> Path:
    candidate = config_path.parent / "config.yaml"
    if candidate.exists():
        return candidate
    return config_path


def _apply_dataclass_overrides(target: Any, overrides: dict[str, Any]) -> None:
    valid_names = {item.name for item in fields(target)}
    for key, value in overrides.items():
        if key not in valid_names:
            continue
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply_dataclass_overrides(current, value)
        else:
            setattr(target, key, value)


def _normalize_symbols(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for item in values:
        raw = str(item).strip().upper().replace("-", "/")
        if not raw:
            continue
        normalized.append(human_symbol(raw))
    return normalized


def _extract_quote_balance(raw_wallet: Any, quote_asset: str, fallback_value: float) -> float:
    if isinstance(raw_wallet, (int, float)):
        return float(raw_wallet)
    if isinstance(raw_wallet, dict):
        if quote_asset in raw_wallet:
            return float(raw_wallet[quote_asset])
        upper_keys = {str(key).upper(): value for key, value in raw_wallet.items()}
        if quote_asset.upper() in upper_keys:
            return float(upper_keys[quote_asset.upper()])
    return fallback_value


def _parse_sqlite_path(db_url: str) -> str:
    if not db_url.startswith("sqlite:///"):
        raise SystemExit("Freqtrade 兼容层当前只支持 SQLite 数据库，例如 sqlite:///data/freqtrade_compat.db")
    return db_url.removeprefix("sqlite:///")


def _resolve_runtime_mode(
    raw_config: dict[str, Any],
    *,
    dry_run: bool | None,
    sandbox: bool,
    monitor: bool,
) -> RuntimeMode:
    quant_raw = raw_config.get("quant") or {}
    exchange_raw = raw_config.get("exchange") or {}
    config_dry_run = bool(raw_config.get("dry_run", True))
    config_sandbox = bool(exchange_raw.get("sandbox", False) or (exchange_raw.get("ccxt_config") or {}).get("sandbox"))
    config_monitor = str(quant_raw.get("mode", "")).lower() == "monitor" or bool(raw_config.get("read_only", False))

    if monitor or config_monitor:
        return RuntimeMode.MONITOR
    if dry_run is True:
        return RuntimeMode.PAPER
    if dry_run is False and (sandbox or config_sandbox):
        return RuntimeMode.TESTNET
    if dry_run is None and config_dry_run:
        return RuntimeMode.PAPER
    if dry_run is None and config_sandbox:
        return RuntimeMode.TESTNET
    raise SystemExit("Freqtrade 路线兼容层默认仍禁止直接实盘。请使用 --dry-run、--sandbox，或 --monitor。")


def translate_freqtrade_to_system(
    config_path: str | Path,
    *,
    strategy_name: str | None = None,
    dry_run: bool | None = None,
    sandbox: bool = False,
    monitor: bool = False,
    dashboard_choice: str | None = None,
) -> tuple[SystemConfig, dict[str, Any], Path]:
    path = Path(config_path).resolve()
    raw = load_raw_freqtrade_config(path)
    base_config_path = _default_system_config_path(path)
    system_config = copy.deepcopy(load_config(base_config_path))
    base_dir = base_config_path.parent.parent

    exchange_raw = raw.get("exchange") or {}
    api_server_raw = raw.get("api_server") or {}
    quant_raw = raw.get("quant") or {}

    market_type = str(raw.get("trading_mode") or exchange_raw.get("market_type") or system_config.exchange.market_type).lower()
    if market_type != "spot":
        raise SystemExit("Freqtrade 路线兼容层当前只支持 Binance Spot。")

    resolved_strategy = resolve_strategy_name(strategy_name or raw.get("strategy") or system_config.strategy.active_strategy)
    system_config.strategy.active_strategy = resolved_strategy
    system_config.app.mode = _resolve_runtime_mode(raw, dry_run=dry_run, sandbox=sandbox, monitor=monitor)

    if raw.get("bot_name"):
        system_config.app.name = str(raw["bot_name"])
    if raw.get("timeframe"):
        system_config.exchange.timeframes = [str(raw["timeframe"])]
    elif raw.get("timeframes"):
        system_config.exchange.timeframes = [str(item) for item in raw.get("timeframes", []) if str(item).strip()]

    pair_whitelist = exchange_raw.get("pair_whitelist") or raw.get("pair_whitelist")
    if pair_whitelist:
        system_config.exchange.symbols = _normalize_symbols(list(pair_whitelist))

    stake_currency = raw.get("stake_currency") or exchange_raw.get("stake_currency")
    if stake_currency:
        system_config.exchange.quote_asset = str(stake_currency).upper()

    if exchange_raw.get("name"):
        system_config.exchange.name = str(exchange_raw["name"]).lower()

    if raw.get("max_open_trades") is not None:
        system_config.risk.max_open_positions = int(raw["max_open_trades"])

    if raw.get("fee") is not None:
        system_config.execution.fee_rate = float(raw["fee"])
        system_config.backtest.fee_rate = float(raw["fee"])

    dry_run_wallet = raw.get("dry_run_wallet")
    wallet_balance = _extract_quote_balance(
        dry_run_wallet,
        system_config.exchange.quote_asset,
        system_config.execution.paper_initial_cash,
    )
    system_config.execution.paper_initial_cash = wallet_balance
    system_config.execution.monitor_reference_cash = wallet_balance

    db_url = raw.get("db_url")
    if db_url:
        system_config.storage.sqlite_path = _parse_sqlite_path(str(db_url))

    if api_server_raw.get("enabled"):
        apply_dashboard_choice(system_config, dashboard_choice or "web")
    else:
        apply_dashboard_choice(system_config, dashboard_choice)

    if api_server_raw.get("listen_ip_address"):
        system_config.app.dashboard.web_host = str(api_server_raw["listen_ip_address"])
    if api_server_raw.get("listen_port") is not None:
        system_config.app.dashboard.web_port = int(api_server_raw["listen_port"])

    if quant_raw.get("risk"):
        _apply_dataclass_overrides(system_config.risk, dict(quant_raw["risk"]))
    if quant_raw.get("execution"):
        _apply_dataclass_overrides(system_config.execution, dict(quant_raw["execution"]))
    if quant_raw.get("exchange"):
        _apply_dataclass_overrides(system_config.exchange, dict(quant_raw["exchange"]))
    if quant_raw.get("backtest"):
        _apply_dataclass_overrides(system_config.backtest, dict(quant_raw["backtest"]))
    if quant_raw.get("app"):
        _apply_dataclass_overrides(system_config.app, dict(quant_raw["app"]))

    strategy_parameters = quant_raw.get("strategy_parameters") or raw.get("strategy_parameters") or {}
    if isinstance(strategy_parameters, dict):
        for key, values in strategy_parameters.items():
            if not isinstance(values, dict):
                continue
            internal_name = resolve_strategy_name(key)
            if internal_name == "ema_trend":
                system_config.strategy.ema_trend.values.update(values)
            elif internal_name == "rsi_bbands_mean_reversion":
                system_config.strategy.rsi_bbands_mean_reversion.values.update(values)

    return system_config, raw, base_dir


def serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {
            field.name: serialize_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): serialize_value(raw) for key, raw in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


def build_show_config_payload(config: SystemConfig, raw_config: dict[str, Any], config_path: str | Path) -> dict[str, Any]:
    return {
        "source_config": str(Path(config_path).resolve()),
        "compat_mode": "freqtrade_route_v1",
        "resolved_mode": config.app.mode.value,
        "resolved_strategy": {
            "internal": config.strategy.active_strategy,
            "public": strategy_public_name(config.strategy.active_strategy),
        },
        "supported_strategies": [
            {
                "internal": item.internal_name,
                "public": item.public_name,
                "description": item.description,
            }
            for item in list_strategy_specs()
        ],
        "raw_freqtrade_config": raw_config,
        "translated_system_config": serialize_value(config),
        "notes": {
            "credentials_source": "仅从 .env 读取，Freqtrade 风格配置中的 key/secret 字段不会直接用于交易。",
            "live_trading": "兼容层默认仍禁止直接实盘。",
        },
    }
