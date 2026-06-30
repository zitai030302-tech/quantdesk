from __future__ import annotations

import argparse
import asyncio
import json
import logging.config
import os
from pathlib import Path

import httpx

from app.config_loader import load_config
from app.control import ControlPlane
from app.dashboard import TerminalDashboard
from app.engine import TradingEngine
from app.types import RuntimeMode, SystemConfig, human_symbol
from app.web_dashboard import CompositeDashboard, WebDashboard
from data.market_data import BinanceMarketDataFeed, CSVReplayMarketDataFeed
from data.market_overview import BinanceMarketOverviewService
from data.network_diagnostics import BinanceNetworkDiagnosticsService
from data.repositories import TradingRepository
from data.rest_client import BinanceRestClient
from data.sqlite import SQLiteStorage
from execution.binance_spot import BinanceSpotAdapter
from execution.paper_broker import PaperBroker
from execution.filters import extract_symbol_rules
from risk.manager import RiskManager
from strategies.registry import build_strategy_from_config, resolve_strategy_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance Spot 多模式量化交易系统")
    parser.add_argument("--mode", required=True, choices=["backtest", "paper", "testnet", "monitor", "live"])
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--csv", default=None, help="用于回测或回放的 CSV 文件")
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--dashboard", default=None, choices=["terminal", "web", "both", "none"])
    parser.add_argument("--max-bars", type=int, default=None, help="限制回放条数，便于测试或调试")
    return parser.parse_args()


def configure_logging(base_dir: Path) -> None:
    logging_path = base_dir / "config" / "logging.yaml"
    if logging_path.exists():
        logging.config.dictConfig(json.loads(logging_path.read_text(encoding="utf-8")))


def ensure_runtime_environment(base_dir: Path) -> None:
    matplotlib_dir = (base_dir / ".matplotlib").resolve()
    matplotlib_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_dir))


def apply_dashboard_choice(config: SystemConfig, choice: str | None) -> None:
    if not choice:
        return
    config.app.dashboard.terminal_enabled = choice in {"terminal", "both"}
    config.app.dashboard.web_enabled = choice in {"web", "both"}
    config.app.dashboard.enabled = choice != "none"


def apply_legacy_overrides(config: SystemConfig, args: argparse.Namespace) -> SystemConfig:
    mode = RuntimeMode(args.mode)
    config.app.mode = mode
    if args.strategy:
        config.strategy.active_strategy = resolve_strategy_name(args.strategy)
    else:
        config.strategy.active_strategy = resolve_strategy_name(config.strategy.active_strategy)
    if args.symbols:
        config.exchange.symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.timeframe:
        config.exchange.timeframes = [args.timeframe]
    apply_dashboard_choice(config, args.dashboard)
    return config


async def load_public_exchange_rules(config: SystemConfig, fallback_exchange_info_path: Path) -> dict:
    clients = [
        BinanceRestClient(
            base_url=config.exchange.market_data_rest_base_url,
            timeout_sec=config.execution.request_timeout_sec,
            recv_window_ms=config.exchange.recv_window_ms,
        ),
        BinanceRestClient(
            base_url=config.exchange.rest_base_url,
            timeout_sec=config.execution.request_timeout_sec,
            recv_window_ms=config.exchange.recv_window_ms,
        ),
    ]
    for client in clients:
        try:
            payload = await client.request("GET", "/api/v3/exchangeInfo")
            return extract_symbol_rules(payload)
        except (httpx.HTTPStatusError, httpx.RequestError):
            continue
    exchange_info = json.loads(fallback_exchange_info_path.read_text(encoding="utf-8"))
    return extract_symbol_rules(exchange_info)


async def run_resolved_config(
    config: SystemConfig,
    base_dir: Path,
    *,
    csv_path: str | None = None,
    max_bars: int | None = None,
) -> None:
    ensure_runtime_environment(base_dir)
    mode = config.app.mode
    if mode == RuntimeMode.LIVE_DISABLED and not config.risk.allow_live:
        raise SystemExit("默认禁止实盘。V1 仅允许使用回测、仿真盘、测试盘和主网只读观察模式。")

    storage = SQLiteStorage(config.storage.sqlite_abspath(base_dir))
    storage.initialize()
    repository = TradingRepository(storage)
    fallback_exchange_info_path = str((base_dir / "tests" / "fixtures" / "exchange_info.json").resolve())
    market_overview_service = BinanceMarketOverviewService(
        rest_base_url=config.exchange.rest_base_url,
        market_data_rest_base_url=config.exchange.market_data_rest_base_url,
        quote_asset=config.exchange.quote_asset,
        limit=300,
        min_quote_volume=1_000_000.0,
    )
    network_diagnostics_service = BinanceNetworkDiagnosticsService()

    if mode == RuntimeMode.BACKTEST:
        from backtest.engine import BacktestEngine

        symbol = human_symbol(config.exchange.symbols[0])
        timeframe = config.exchange.timeframes[0]
        exchange_info = json.loads((base_dir / "tests" / "fixtures" / "exchange_info.json").read_text(encoding="utf-8"))
        rules = extract_symbol_rules(exchange_info)
        strategy = build_strategy_from_config(config.strategy.active_strategy, symbol, timeframe, config.strategy)
        engine = BacktestEngine(
            backtest_config=config.backtest,
            risk_config=config.risk,
            strategy=strategy,
            rule=rules[symbol.replace("/", "")],
        )
        result = engine.run(csv_path or config.backtest.default_csv, symbol=symbol, timeframe=timeframe)
        print(f"回测收益率：{result.total_return:.2%}")
        print(f"最大回撤：{result.max_drawdown:.2%}")
        print(f"胜率：{result.win_rate:.2%}")
        print(f"夏普比率：{result.sharpe:.2f}")
        print(f"权益曲线：{result.equity_curve_path}")
        return

    market_feed = (
        CSVReplayMarketDataFeed(csv_path)
        if csv_path
        else BinanceMarketDataFeed(
            config.exchange,
            mode,
            fallback_csv_path=str((base_dir / config.backtest.default_csv).resolve())
            if mode in {RuntimeMode.PAPER, RuntimeMode.MONITOR}
            else None,
        )
    )
    risk_manager = RiskManager(config.risk, mode)

    if mode == RuntimeMode.PAPER:
        rules = await load_public_exchange_rules(config, Path(fallback_exchange_info_path))
        adapter = PaperBroker(
            rules=rules,
            initial_cash=config.execution.paper_initial_cash,
            fee_rate=config.execution.fee_rate,
            slippage_bps=config.risk.slippage_bps,
            quote_asset=config.exchange.quote_asset,
        )
    elif mode == RuntimeMode.TESTNET:
        adapter = BinanceSpotAdapter(
            rest_base_url=config.exchange.testnet_rest_base_url,
            ws_api_url=config.exchange.testnet_ws_api_url,
            api_key=config.env.get("BINANCE_TESTNET_API_KEY", ""),
            api_secret=config.env.get("BINANCE_TESTNET_API_SECRET", ""),
            timeout_sec=config.execution.request_timeout_sec,
            recv_window_ms=config.exchange.recv_window_ms,
            sync_interval_sec=config.execution.sync_interval_sec,
            quote_asset=config.exchange.quote_asset,
            reconnect_delay_sec=config.exchange.user_stream_reconnect_delay_sec,
            market_data_rest_base_url=None,
            fallback_exchange_info_path=None,
            mode_label="testnet",
        )
    else:
        adapter = BinanceSpotAdapter(
            rest_base_url=config.exchange.rest_base_url,
            ws_api_url=config.exchange.ws_api_url,
            api_key=config.env.get("BINANCE_MAINNET_API_KEY", ""),
            api_secret=config.env.get("BINANCE_MAINNET_API_SECRET", ""),
            timeout_sec=config.execution.request_timeout_sec,
            recv_window_ms=config.exchange.recv_window_ms,
            sync_interval_sec=config.execution.sync_interval_sec,
            quote_asset=config.exchange.quote_asset,
            reconnect_delay_sec=config.exchange.user_stream_reconnect_delay_sec,
            market_data_rest_base_url=config.exchange.market_data_rest_base_url,
            fallback_exchange_info_path=fallback_exchange_info_path,
            read_only=True,
            planning_quote_balance=config.execution.monitor_reference_cash,
            mode_label="monitor",
        )

    dashboards: list[object] = []
    control_plane = ControlPlane()
    if config.app.dashboard.enabled and config.app.dashboard.terminal_enabled:
        dashboards.append(TerminalDashboard())
    if config.app.dashboard.enabled and config.app.dashboard.web_enabled:
        try:
            web_dashboard = WebDashboard(
                host=config.app.dashboard.web_host,
                port=config.app.dashboard.web_port,
                control_plane=control_plane,
                auto_open_browser=os.environ.get("QUANT_AUTO_OPEN_BROWSER") == "1",
                browser_url=os.environ.get("QUANT_AUTO_OPEN_URL"),
            )
        except OSError as exc:
            raise SystemExit(
                f"无法在 {config.app.dashboard.web_host}:{config.app.dashboard.web_port} 启动 Web 控制台：{exc}"
            ) from exc
        dashboards.append(web_dashboard)
        print(f"Web 控制台：http://{config.app.dashboard.web_host}:{web_dashboard.port}")
    dashboard = CompositeDashboard(dashboards) if dashboards else None
    engine = TradingEngine(
        config=config,
        repository=repository,
        market_data_feed=market_feed,
        adapter=adapter,
        risk_manager=risk_manager,
        dashboard=dashboard,
        control_plane=control_plane,
        market_overview_service=market_overview_service,
        network_diagnostics_service=network_diagnostics_service,
    )
    if "web_dashboard" in locals():
        web_dashboard.set_analyze_handler(
            lambda symbol, timeframe, strategy=None: engine.run_symbol_analysis_sync(
                symbol=symbol,
                timeframe=timeframe,
                strategy_name=strategy,
            )
        )
    await engine.run(max_bars=max_bars)


async def run_async(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    base_dir = Path(args.config).resolve().parent.parent
    configure_logging(base_dir)
    config = apply_legacy_overrides(config, args)
    await run_resolved_config(
        config,
        base_dir,
        csv_path=args.csv,
        max_bars=args.max_bars,
    )


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_async(args))
    except KeyboardInterrupt:
        print("交易会话已停止。")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise SystemExit(
            f"无法访问 Binance API（HTTP {status_code}）。"
            "如果你当前网络受限，可以使用 --csv 运行仿真盘或主网观察回放，"
            "也可以直接用桌面启动器打开仿真盘/主网观察模式；系统会先尝试官方只读行情端点，再自动回退到本地示例数据。"
        ) from exc
    except httpx.RequestError as exc:
        raise SystemExit(
            "由于网络异常，暂时无法访问 Binance API。"
            "你仍然可以使用 --csv 本地回放，或直接用桌面启动器运行仿真盘/主网观察模式。"
        ) from exc
