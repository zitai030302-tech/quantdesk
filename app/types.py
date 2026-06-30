from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RuntimeMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    TESTNET = "testnet"
    MONITOR = "monitor"
    LIVE_DISABLED = "live"


class RiskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    PROTECT = "protect"


@dataclass(slots=True)
class DashboardConfig:
    enabled: bool = True
    terminal_enabled: bool = True
    web_enabled: bool = False
    refresh_interval_sec: float = 1.0
    max_rows: int = 8
    web_host: str = "127.0.0.1"
    web_port: int = 8765


@dataclass(slots=True)
class AlertsConfig:
    console: bool = True


@dataclass(slots=True)
class AppConfig:
    name: str = "binance-spot-quant"
    timezone: str = "Asia/Shanghai"
    mode: RuntimeMode = RuntimeMode.PAPER
    log_level: str = "INFO"
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)


@dataclass(slots=True)
class ExchangeConfig:
    name: str = "binance"
    market_type: str = "spot"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframes: list[str] = field(default_factory=lambda: ["1m", "5m"])
    rest_base_url: str = "https://api.binance.com"
    ws_base_url: str = "wss://stream.binance.com:9443/ws"
    ws_api_url: str = "wss://ws-api.binance.com:443/ws-api/v3"
    market_data_rest_base_url: str = "https://data-api.binance.vision"
    market_data_ws_base_url: str = "wss://data-stream.binance.vision/ws"
    testnet_rest_base_url: str = "https://testnet.binance.vision"
    testnet_ws_base_url: str = "wss://stream.testnet.binance.vision/ws"
    testnet_ws_api_url: str = "wss://ws-api.testnet.binance.vision/ws-api/v3"
    warmup_limit: int = 300
    recv_window_ms: int = 5000
    subscribe_ticker: bool = False
    subscribe_depth: bool = False
    quote_asset: str = "USDT"
    user_stream_reconnect_delay_sec: float = 2.0


@dataclass(slots=True)
class StrategyParams:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyConfig:
    active_strategy: str = "ema_trend"
    ema_trend: StrategyParams = field(default_factory=StrategyParams)
    rsi_bbands_mean_reversion: StrategyParams = field(default_factory=StrategyParams)


@dataclass(slots=True)
class RiskConfig:
    max_trade_risk_pct: float = 0.005
    daily_loss_limit_pct: float = 0.02
    max_loss_streak: int = 3
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    atr_take_profit_mult: float = 3.0
    slippage_bps: float = 8.0
    max_open_positions: int = 1
    allow_live: bool = False
    allow_margin: bool = False
    allow_futures: bool = False
    allow_martingale: bool = False
    allow_grid_average_down: bool = False


@dataclass(slots=True)
class ExecutionConfig:
    retry_attempts: int = 3
    retry_backoff_sec: float = 1.0
    request_timeout_sec: float = 10.0
    fee_rate: float = 0.001
    paper_initial_cash: float = 10000.0
    sync_interval_sec: float = 3.0
    paper_fill_model: str = "close_with_slippage"
    default_order_type: str = "market"
    monitor_reference_cash: float = 10000.0


@dataclass(slots=True)
class StorageConfig:
    sqlite_path: str = "data/trading.db"
    artifact_dir: str = "artifacts"
    log_path: str = "logs/system.log"

    def sqlite_abspath(self, base_dir: Path) -> Path:
        return (base_dir / self.sqlite_path).resolve()

    def artifact_abspath(self, base_dir: Path) -> Path:
        return (base_dir / self.artifact_dir).resolve()


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 10000.0
    fee_rate: float = 0.001
    default_csv: str = "tests/fixtures/btcusdt_1m_sample.csv"
    output_dir: str = "artifacts"


@dataclass(slots=True)
class SystemConfig:
    app: AppConfig = field(default_factory=AppConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    env: dict[str, str] = field(default_factory=dict)


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def human_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol.upper()
    if symbol.endswith("USDT"):
        return f"{symbol[:-4].upper()}/USDT"
    return symbol.upper()
