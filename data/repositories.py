from __future__ import annotations

import json
from typing import Iterable

from data.models import Bar, FillRecord, OrderRecord, PnLSnapshot, Position, RiskEvent, Signal
from data.sqlite import SQLiteStorage


class TradingRepository:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def save_candle(self, bar: Bar) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO candles (
                symbol, timeframe, open_time, close_time, open, high, low, close,
                volume, quote_volume, trades, is_closed, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bar.symbol,
                bar.timeframe,
                bar.open_time.isoformat(),
                bar.close_time.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.quote_volume,
                bar.trades,
                int(bar.is_closed),
                bar.source,
            ),
        )

    def save_signal(self, signal: Signal) -> None:
        self.storage.execute(
            """
            INSERT INTO signals (
                strategy_name, symbol, timeframe, signal_type, timestamp, reason, strength,
                stop_loss, take_profit, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.strategy_name,
                signal.symbol,
                signal.timeframe,
                signal.signal_type.value,
                signal.timestamp.isoformat(),
                signal.reason,
                signal.strength,
                signal.stop_loss,
                signal.take_profit,
                json.dumps(signal.metadata, ensure_ascii=True),
            ),
        )

    def save_order(self, order: OrderRecord) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO orders (
                order_id, client_order_id, symbol, side, order_type, status, quantity, price,
                filled_quantity, average_price, created_at, updated_at, mode, reduce_only,
                stop_loss, take_profit, reason, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.client_order_id,
                order.symbol,
                order.side.value,
                order.order_type.value,
                order.status.value,
                order.quantity,
                order.price,
                order.filled_quantity,
                order.average_price,
                order.created_at.isoformat(),
                order.updated_at.isoformat(),
                order.mode,
                int(order.reduce_only),
                order.stop_loss,
                order.take_profit,
                order.reason,
                json.dumps(order.metadata, ensure_ascii=True),
            ),
        )

    def save_fill(self, fill: FillRecord) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO fills (
                fill_id, order_id, symbol, side, quantity, price, fee, fee_asset, realized_pnl, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.fill_id,
                fill.order_id,
                fill.symbol,
                fill.side.value,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.fee_asset,
                fill.realized_pnl,
                fill.timestamp.isoformat(),
            ),
        )

    def save_position(self, position: Position) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO positions (
                symbol, quantity, average_price, market_price, realized_pnl, unrealized_pnl,
                stop_loss, take_profit, opened_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.symbol,
                position.quantity,
                position.average_price,
                position.market_price,
                position.realized_pnl,
                position.unrealized_pnl,
                position.stop_loss,
                position.take_profit,
                position.opened_at.isoformat() if position.opened_at else None,
                position.updated_at.isoformat() if position.updated_at else None,
                json.dumps(position.metadata, ensure_ascii=True),
            ),
        )

    def save_daily_pnl(self, snapshot: PnLSnapshot) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO daily_pnl (date, realized_pnl, unrealized_pnl, net_asset_value)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot.date, snapshot.realized_pnl, snapshot.unrealized_pnl, snapshot.net_asset_value),
        )

    def save_risk_event(self, event: RiskEvent) -> None:
        self.storage.execute(
            """
            INSERT INTO risk_events (timestamp, event_type, message, status, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.timestamp.isoformat(),
                event.event_type,
                event.message,
                event.status.value,
                json.dumps(event.details, ensure_ascii=True),
            ),
        )

    def recent_orders(self, limit: int = 10) -> list[dict]:
        rows = self.storage.fetchall(
            "SELECT * FROM orders ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def recent_signals(self, limit: int = 10) -> list[dict]:
        rows = self.storage.fetchall(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def recent_risk_events(self, limit: int = 10) -> list[dict]:
        rows = self.storage.fetchall(
            "SELECT * FROM risk_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def list_candles(self, symbol: str, timeframe: str) -> list[dict]:
        rows = self.storage.fetchall(
            "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? ORDER BY open_time ASC",
            (symbol, timeframe),
        )
        return [dict(row) for row in rows]

    def seed_candles(self, bars: Iterable[Bar]) -> None:
        for bar in bars:
            self.save_candle(bar)
