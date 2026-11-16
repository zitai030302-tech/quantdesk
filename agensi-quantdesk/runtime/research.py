"""Research reports from the existing QuantDesk engine and strategies."""
from dataclasses import asdict
import math
import re
from pathlib import Path

from .core.app.types import BacktestConfig, RiskConfig
from .core.backtest.engine import BacktestEngine
from .core.backtest.metrics import periods_per_year
from .core.strategies.registry import build_strategy_from_config
from .inputs import TIMEFRAMES, fields, number, read_bars, strategy_spec, symbol_rule


def metrics(result, equity, annual_periods, seconds):
    trades = result.trades
    closed = sum(trade["exit_price"] is not None for trade in trades)
    returns = [current / previous - 1 for previous, current in zip(equity, equity[1:])]
    mean = sum(returns) / len(returns)
    downside = math.sqrt(sum(min(0, rate) ** 2 for rate in returns) / len(returns))
    variance = sum((rate - mean) ** 2 for rate in returns)
    fees = sum(trade["entry_fee"] + trade["exit_fee"] for trade in trades)
    slippage = sum(trade["slippage_cost"] for trade in trades)
    notional = sum(trade["quantity"] * (trade["entry_price"] + (trade["exit_price"] or 0)) for trade in trades)
    # Avoid extrapolating very short fixture runs as if they were long samples.
    annual_return = math.expm1(math.log(equity[-1] / equity[0]) * 31_536_000 / seconds) if seconds >= 30 * 86400 else None
    return {
        "total_return": result.total_return,
        "annualized_return": annual_return,
        "sharpe_ratio": result.sharpe if variance > 0 else None,
        "sortino_ratio": mean / downside * math.sqrt(annual_periods) if downside else None,
        "maximum_drawdown": result.max_drawdown,
        "win_rate": result.win_rate if closed else None,
        "trade_count": closed,
        "open_trade_count": len(trades) - closed,
        "fees": fees,
        "slippage_cost": slippage,
        "transaction_costs": fees + slippage,
        "turnover": notional / (sum(equity) / len(equity)),
        "ending_equity": equity[-1],
    }


def run(request, csv_path: Path, mode: str):
    fields(request, allowed={"symbol", "timeframe", "strategies", "initial_cash", "fee_bps",
                             "slippage_bps", "risk_per_trade", "data_source"},
           required={"symbol", "timeframe", "strategies"}, label="research request")
    symbol = request["symbol"]
    rule = symbol_rule(symbol)
    timeframe = request["timeframe"]
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
        raise ValueError("unsupported timeframe")
    strategies = request["strategies"]
    low, high = (1, 1) if mode == "backtest" else (2, 6)
    if not isinstance(strategies, list) or not low <= len(strategies) <= high:
        raise ValueError(f"{mode} requires {low} to {high} strategy configurations")
    specs = [strategy_spec(value) for value in strategies]
    if len({(name, tuple(params.items())) for name, params, _ in specs}) != len(specs):
        raise ValueError("duplicate strategy configurations")
    cash = number(request.get("initial_cash", 10000), 1, 1e10, "initial_cash")
    fee = number(request.get("fee_bps", 10), 0, 200, "fee_bps")
    slippage = number(request.get("slippage_bps", 5), 0, 200, "slippage_bps")
    risk_fraction = number(request.get("risk_per_trade", 0.005), 0.0001, 0.05, "risk_per_trade")
    source = request.get("data_source", "User-supplied CSV")
    if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .,/_()+:-]{0,119}", source):
        raise ValueError("data_source must be a short plain-text source label")

    bars, digest = read_bars(csv_path, symbol, timeframe)
    risk = RiskConfig(max_trade_risk_pct=risk_fraction, slippage_bps=slippage)
    for name, params, _ in specs:
        periods = [risk.atr_period, *(val for key, val in params.items() if key.endswith("_period"))]
        required_bars = max(periods) + 2
        if len(bars) < required_bars:
            raise ValueError(f"{name} needs at least {required_bars} bars to warm up and execute")

    report = {
        "mode": mode,
        "data": {"source": source, "symbol": symbol, "quote_asset": rule.quote_asset,
                 "timeframe": timeframe, "bars": len(bars), "sha256": digest,
                 "start": bars[0].open_time.isoformat(), "last_close": bars[-1].close_time.isoformat()},
        "assumptions": {"initial_cash": cash, "fee_bps": fee, "slippage_bps": slippage,
                        "periods_per_year": periods_per_year(timeframe),
                        "risk": asdict(risk), "exchange_rule": asdict(rule)},
        "runs": [],
    }
    metrics_rows, trade_rows, equity_rows = [], [], []
    for index, (name, params, strategy_config) in enumerate(specs, 1):
        strategy = build_strategy_from_config(name, symbol, timeframe, strategy_config)
        engine = BacktestEngine(BacktestConfig(initial_cash=cash, fee_rate=fee / 10_000), risk, strategy, rule,
                                slippage_bps=slippage)
        result = engine.run_bars(bars, symbol, timeframe)
        equity = [cash, *engine.broker.equity_curve]
        values = metrics(result, equity, periods_per_year(timeframe), len(bars) * TIMEFRAMES[timeframe])
        report["runs"].append({"run": index, "strategy": name, "parameters": params, "metrics": values})
        metrics_rows.append({"run": index, "strategy": name, **values})
        trade_rows.extend({"run": index, **trade} for trade in result.trades)
        timestamps = [report["data"]["start"], *(bar.close_time.isoformat() for bar in bars)]
        equity_rows.extend({"run": index, "timestamp": timestamp, "equity": value}
                           for timestamp, value in zip(timestamps, equity))

    trades_fields = ("run", "symbol", "entry_time", "entry_price", "exit_time", "exit_price", "quantity",
                     "pnl", "entry_fee", "exit_fee", "slippage_cost", "exit_reason", "reason")
    return report, {"metrics": (tuple(metrics_rows[0]), metrics_rows),
                    "trades": (trades_fields, trade_rows),
                    "equity": (("run", "timestamp", "equity"), equity_rows)}
