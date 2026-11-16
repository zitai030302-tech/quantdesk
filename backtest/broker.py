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
    exit_fee: float = 0.0
    slippage_cost: float = 0.0
    exit_reason: str | None = None


class BacktestBroker:
    def __init__(self, initial_cash: float, fee_rate: float, slippage_bps: float = 0.0, *, quote_asset: str = "USDT") -> None:
        self.cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage = slippage_bps / 10_000
        self.quote_asset = quote_asset
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
            entry_price = bar.open * (1 + self.slippage)
            fee = quantity * entry_price * self.fee_rate
            cost = quantity * entry_price + fee
            stop = self.pending_entry["stop_loss"]
            target = self.pending_entry["take_profit"]
            if self.cash >= cost and 0 < stop < bar.open and entry_price < target:
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
                        slippage_cost=quantity * (entry_price - bar.open),
                        reason=self.pending_entry["reason"],
                    )
                )
            self.pending_entry = None

        if self.position.is_open:
            reference = None
            exit_reason = ""
            exit_time = bar.close_time  # Timestamp is only a bar label for intrabar fills.
            stop = self.position.stop_loss
            target = self.position.take_profit
            if self.pending_exit:
                reference = bar.open
                exit_reason = self.pending_exit["reason"]
                exit_time = bar.open_time
            elif stop is not None and bar.open <= stop:
                reference, exit_reason, exit_time = bar.open, "stop_loss", bar.open_time
            elif target is not None and bar.open >= target:
                reference, exit_reason, exit_time = bar.open, "take_profit", bar.open_time
            elif stop is not None and bar.low <= stop:
                reference, exit_reason = stop, "stop_loss"
            elif target is not None and bar.high >= target:
                reference, exit_reason = target, "take_profit"

            if reference is not None:
                exit_price = reference * (1 - self.slippage)
                fee = self.position.quantity * exit_price * self.fee_rate
                pnl = (exit_price - self.position.average_price) * self.position.quantity - fee
                self.cash += (self.position.quantity * exit_price) - fee
                trade = self.trades[-1]
                trade.exit_time = exit_time
                trade.exit_price = exit_price
                trade.exit_fee = fee
                trade.slippage_cost += self.position.quantity * (reference - exit_price)
                trade.exit_reason = exit_reason
                trade.pnl = pnl - trade.fee
                fill = FillRecord(
                    fill_id=f"bt-{len(self.closed_fill_records) + 1}",
                    order_id=f"bt-order-{len(self.closed_fill_records) + 1}",
                    symbol=self.position.symbol,
                    side=Side.SELL,
                    quantity=self.position.quantity,
                    price=exit_price,
                    fee=fee,
                    fee_asset=self.quote_asset,
                    realized_pnl=trade.pnl,
                    timestamp=exit_time,
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
