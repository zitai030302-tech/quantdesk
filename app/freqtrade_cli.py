from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from app.cli import configure_logging, run_resolved_config
from app.freqtrade_compat import build_show_config_payload, translate_freqtrade_to_system
from app.types import RuntimeMode
from strategies.registry import list_strategy_specs, strategy_public_name


FREQTRADE_COMMANDS = {"trade", "backtesting", "webserver", "show-config", "list-strategies"}


def should_handle_freqtrade_route(argv: list[str] | None = None) -> bool:
    args = argv or sys.argv[1:]
    return bool(args) and args[0] in FREQTRADE_COMMANDS


def _add_common_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", default="config/freqtrade_compat.json", help="Freqtrade 风格兼容配置文件")
    parser.add_argument("--strategy", default=None, help="策略名称，可用公开名或内部名")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="使用仿真盘 dry-run 模式")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="关闭 dry-run，需配合 --sandbox")
    parser.set_defaults(dry_run=None)
    parser.add_argument("--sandbox", action="store_true", help="使用 Binance Spot Testnet")
    parser.add_argument("--monitor", action="store_true", help="主网只读观察模式，不下单")
    parser.add_argument("--csv", default=None, help="使用本地 CSV 做回放或回测")
    parser.add_argument("--max-bars", type=int, default=None, help="限制处理条数，便于调试")
    parser.add_argument("--dashboard", default=None, choices=["terminal", "web", "both", "none"], help="控制台展示方式")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freqtrade 路线兼容启动器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trade = subparsers.add_parser("trade", help="按 Freqtrade 风格启动交易会话")
    _add_common_runtime_args(trade)
    trade.add_argument("--webserver", action="store_true", help="同时打开 Web 控制台")

    webserver = subparsers.add_parser("webserver", help="按 Freqtrade 风格启动 Web 控制台模式")
    _add_common_runtime_args(webserver)

    backtesting = subparsers.add_parser("backtesting", help="按 Freqtrade 风格运行回测")
    backtesting.add_argument("-c", "--config", default="config/freqtrade_compat.json", help="Freqtrade 风格兼容配置文件")
    backtesting.add_argument("--strategy", default=None, help="策略名称，可用公开名或内部名")
    backtesting.add_argument("--csv", default=None, help="用于回测的 CSV 文件")
    backtesting.add_argument("--max-bars", type=int, default=None, help="限制回放条数，便于测试")

    show_config = subparsers.add_parser("show-config", help="显示兼容配置解析后的结果")
    show_config.add_argument("-c", "--config", default="config/freqtrade_compat.json", help="Freqtrade 风格兼容配置文件")
    show_config.add_argument("--strategy", default=None, help="策略名称，可用公开名或内部名")
    show_config.add_argument("--dry-run", dest="dry_run", action="store_true")
    show_config.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    show_config.set_defaults(dry_run=None)
    show_config.add_argument("--sandbox", action="store_true")
    show_config.add_argument("--monitor", action="store_true")

    subparsers.add_parser("list-strategies", help="列出兼容层支持的策略")
    return parser.parse_args(argv)


async def _run_trade_command(args: argparse.Namespace, dashboard_choice: str | None = None) -> None:
    config, _raw, base_dir = translate_freqtrade_to_system(
        args.config,
        strategy_name=args.strategy,
        dry_run=args.dry_run,
        sandbox=args.sandbox,
        monitor=args.monitor,
        dashboard_choice=dashboard_choice or args.dashboard,
    )
    configure_logging(base_dir)
    await run_resolved_config(
        config,
        base_dir,
        csv_path=args.csv,
        max_bars=args.max_bars,
    )


def _run_show_config(args: argparse.Namespace) -> None:
    config, raw, _base_dir = translate_freqtrade_to_system(
        args.config,
        strategy_name=args.strategy,
        dry_run=args.dry_run,
        sandbox=args.sandbox,
        monitor=args.monitor,
    )
    payload = build_show_config_payload(config, raw, args.config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_list_strategies() -> None:
    print("可用策略：")
    for spec in list_strategy_specs():
        print(f"- {spec.public_name} ({spec.internal_name})：{spec.description}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.command == "list-strategies":
            _run_list_strategies()
            return
        if args.command == "show-config":
            _run_show_config(args)
            return
        if args.command == "backtesting":
            config, _raw, base_dir = translate_freqtrade_to_system(
                args.config,
                strategy_name=args.strategy,
            )
            configure_logging(base_dir)
            config.app.mode = RuntimeMode.BACKTEST
            print(f"回测策略：{strategy_public_name(config.strategy.active_strategy)}")
            asyncio.run(
                run_resolved_config(
                    config,
                    base_dir,
                    csv_path=args.csv,
                    max_bars=args.max_bars,
                )
            )
            return

        forced_dashboard = args.dashboard
        if args.command == "webserver" and forced_dashboard is None:
            forced_dashboard = "web"
        elif args.command == "trade" and getattr(args, "webserver", False) and forced_dashboard is None:
            forced_dashboard = "both"

        asyncio.run(_run_trade_command(args, dashboard_choice=forced_dashboard))
    except KeyboardInterrupt:
        print("交易会话已停止。")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise SystemExit(
            f"无法访问 Binance API（HTTP {status_code}）。"
            "你可以使用 --dry-run 配合本地 CSV 回放，或让系统自动回退到官方只读行情端点。"
        ) from exc
    except httpx.RequestError as exc:
        raise SystemExit(
            "由于网络异常，暂时无法访问 Binance API。你仍然可以用 --csv 跑回测或本地回放。"
        ) from exc
