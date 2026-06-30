from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data.models import FillRecord, Position, Side


@dataclass(slots=True)
class BacktestTrade:
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    quantity: float = 0.0
    fee: float = 0.0
    pnl: float = 0.0
    reason: str = ""


class BacktestBroker:
    def __init__(self, initial_cash: float, fee_rate: float) -> None:
        self.cash = initial_cash
        self.fee_rate = fee_rate
        self.position = Position(symbol="BTCUSDT")
        self.pending_entry: dict | None = None
        self.pending_exit: dict | None = None
        self.equity_curve: list[float] = []
        self.trades: list[BacktestTrade] = []
        self.closed_fill_records: list[FillRecord] = []

    def queue_entry(self, symbol: str, time: datetime, quantity: float, stop_loss: float, take_profit: float, reason: str) -> None:
        self.pending_entry = {
            "symbol": symbol,
            "time": time,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": reason,
        }

    def queue_exit(self, time: datetime, reason: str) -> None:
        if self.position.is_open:
            self.pending_exit = {"time": time, "reason": reason}

    def process_bar(self, bar) -> list[FillRecord]:
        fills: list[FillRecord] = []
        if self.pending_entry:
            quantity = self.pending_entry["quantity"]
            entry_price = bar.open
            fee = quantity * entry_price * self.fee_rate
            cost = quantity * entry_price + fee
            if self.cash >= cost:
                self.cash -= cost
                self.position.symbol = bar.symbol.replace("/", "").upper()
                self.position.quantity = quantity
                self.position.average_price = entry_price
                self.position.market_price = bar.close
                self.position.stop_loss = self.pending_entry["stop_loss"]
                self.position.take_profit = self.pending_entry["take_profit"]
                self.position.opened_at = bar.open_time
                self.trades.append(
                    BacktestTrade(
                        symbol=bar.symbol,
                        entry_time=bar.open_time,
                        entry_price=entry_price,
                        quantity=quantity,
                        fee=fee,
                        reason=self.pending_entry["reason"],
                    )
                )
            self.pending_entry = None

        if self.position.is_open:
            exit_price = None
            exit_reason = ""
            if self.position.stop_loss is not None and bar.low <= self.position.stop_loss:
                exit_price = self.position.stop_loss
                exit_reason = "stop_loss"
            elif self.position.take_profit is not None and bar.high >= self.position.take_profit:
                exit_price = self.position.take_profit
                exit_reason = "take_profit"
            elif self.pending_exit:
                exit_price = bar.open
                exit_reason = self.pending_exit["reason"]

            if exit_price is not None:
                fee = self.position.quantity * exit_price * self.fee_rate
                pnl = (exit_price - self.position.average_price) * self.position.quantity - fee
                self.cash += (self.position.quantity * exit_price) - fee
                trade = self.trades[-1]
                trade.exit_time = bar.close_time
                trade.exit_price = exit_price
                trade.pnl = pnl - trade.fee
                fill = FillRecord(
                    fill_id=f"bt-{len(self.closed_fill_records) + 1}",
                    order_id=f"bt-order-{len(self.closed_fill_records) + 1}",
                    symbol=self.position.symbol,
                    side=Side.SELL,
                    quantity=self.position.quantity,
                    price=exit_price,
                    fee=fee,
                    fee_asset="USDT",
                    realized_pnl=trade.pnl,
                    timestamp=bar.close_time,
                )
                fills.append(fill)
                self.closed_fill_records.append(fill)
                self.position = Position(symbol=self.position.symbol)
                self.pending_exit = None
        self.mark_to_market(bar.close)
        return fills

    def mark_to_market(self, price: float) -> None:
        equity = self.cash
        if self.position.is_open:
            equity += self.position.quantity * price
        self.equity_curve.append(equity)
