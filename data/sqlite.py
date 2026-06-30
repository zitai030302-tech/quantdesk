from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    quote_volume REAL NOT NULL,
    trades INTEGER NOT NULL,
    is_closed INTEGER NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(symbol, timeframe, open_time)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    reason TEXT NOT NULL,
    strength REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    filled_quantity REAL NOT NULL,
    average_price REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    reduce_only INTEGER NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    fee_asset TEXT NOT NULL,
    realized_pnl REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    market_price REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    opened_at TEXT,
    updated_at TEXT,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    net_asset_value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL
);
"""


class SQLiteStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def execute(self, query: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        cursor = self.connection.execute(query, params)
        self.connection.commit()
        return cursor

    def executemany(self, query: str, rows: list[tuple]) -> None:
        self.connection.executemany(query, rows)
        self.connection.commit()

    def fetchall(self, query: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, params))

    def fetchone(self, query: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.connection.execute(query, params).fetchone()

    def close(self) -> None:
        self.connection.close()
