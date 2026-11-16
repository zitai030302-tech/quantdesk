from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.types import BacktestConfig, RiskConfig, RuntimeMode
from data.csv_loader import load_ohlcv_csv
from data.models import AccountSnapshot, Balance, Bar, ExchangeRule, SignalType
from risk.manager import RiskManager
from strategies.base import BaseStrategy
from backtest.broker import BacktestBroker
from backtest.metrics import max_drawdown, periods_per_year, sharpe_ratio, win_rate
from backtest.report import save_equity_curve


@dataclass(slots=True)
class BacktestResult:
    total_return: float
    max_drawdown: float
    win_rate: float
    sharpe: float
    trades: list[dict]
    equity_curve_path: Path | None


class BacktestEngine:
    def __init__(
        self,
        backtest_config: BacktestConfig,
        risk_config: RiskConfig,
        strategy: BaseStrategy,
        rule: ExchangeRule,
        *,
        slippage_bps: float = 0.0,
    ) -> None:
        self.config = backtest_config
        self.risk_manager = RiskManager(risk_config, RuntimeMode.BACKTEST, fee_rate=backtest_config.fee_rate)
        self.strategy = strategy
        self.rule = rule
        self.broker = BacktestBroker(
            backtest_config.initial_cash, backtest_config.fee_rate, slippage_bps, quote_asset=rule.quote_asset,
        )

    def run(self, csv_path: str, symbol: str, timeframe: str) -> BacktestResult:
        bars = load_ohlcv_csv(csv_path, symbol=symbol, timeframe=timeframe)
        return self.run_bars(bars, symbol, timeframe, save_chart=True)

    def run_bars(
        self, bars: list[Bar], symbol: str, timeframe: str, *, save_chart: bool = False,
    ) -> BacktestResult:
        annual_periods = periods_per_year(timeframe)
        timestamps: list[str] = []
        for bar in bars:
            prior_nav = self.broker.equity_curve[-1] if self.broker.equity_curve else self.config.initial_cash
            # Roll the UTC risk day before processing any fill on this bar.
            self.risk_manager.observe_account(AccountSnapshot(bar.open_time, {}, prior_nav, self.broker.cash))
            for fill in self.broker.process_bar(bar):
                self.risk_manager.observe_account(AccountSnapshot(fill.timestamp, {}, prior_nav, self.broker.cash))
                self.risk_manager.on_trade_closed(fill)
            account = AccountSnapshot(
                timestamp=bar.close_time,
                balances={self.rule.quote_asset: Balance(asset=self.rule.quote_asset, free=self.broker.cash)},
                net_asset_value=self.broker.equity_curve[-1] if self.broker.equity_curve else self.config.initial_cash,
                available_quote_balance=self.broker.cash,
            )
            position = self.broker.position if self.broker.position.is_open else None
            self.strategy.on_bar(bar)
            signal = self.strategy.generate_signal(bar, position)
            if signal.signal_type == SignalType.BUY:
                decision = self.risk_manager.evaluate_signal(signal, account, position, self.rule, self.strategy.bars)
                if decision.allowed:
                    self.broker.queue_entry(
                        symbol=symbol,
                        time=bar.close_time,
                        quantity=decision.quantity,
                        stop_loss=decision.stop_loss or (bar.close * 0.99),
                        take_profit=decision.take_profit or (bar.close * 1.01),
                        reason=signal.reason,
                    )
            elif signal.signal_type in {SignalType.FLAT, SignalType.SELL}:
                self.broker.queue_exit(bar.close_time, signal.reason)

            timestamps.append(bar.close_time.isoformat())

        equity_curve = [self.config.initial_cash, *self.broker.equity_curve]
        returns = []
        for index in range(1, len(equity_curve)):
            previous = equity_curve[index - 1]
            if previous <= 0:
                returns.append(0.0)
            else:
                returns.append((equity_curve[index] - previous) / previous)
        equity_curve_path = None
        if save_chart:
            output_path = Path(self.config.output_dir) / f"equity_curve_{symbol.replace('/', '').lower()}_{timeframe}.png"
            equity_curve_path = save_equity_curve(output_path, timestamps, self.broker.equity_curve)
        trade_pnls = [trade.pnl for trade in self.broker.trades if trade.exit_price is not None]
        total_return = (equity_curve[-1] - self.config.initial_cash) / self.config.initial_cash
        return BacktestResult(
            total_return=total_return,
            max_drawdown=max_drawdown(equity_curve),
            win_rate=win_rate(trade_pnls),
            sharpe=sharpe_ratio(returns, periods_per_year=annual_periods),
            trades=[
                {
                    "symbol": trade.symbol,
                    "entry_time": trade.entry_time.isoformat(),
                    "entry_price": trade.entry_price,
                    "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl if trade.exit_price is not None else None,
                    "entry_fee": trade.fee,
                    "exit_fee": trade.exit_fee,
                    "slippage_cost": trade.slippage_cost,
                    "exit_reason": trade.exit_reason,
                    "reason": trade.reason,
                }
                for trade in self.broker.trades
            ],
            equity_curve_path=equity_curve_path,
        )

