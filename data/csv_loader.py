from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

from data.models import Bar


def _parse_timestamp(raw: str) -> datetime:
    if raw.isdigit():
        millis = int(raw)
        if millis > 10_000_000_000:
            return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(millis, tz=timezone.utc)
    text = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_ohlcv_csv(path: str | Path, symbol: str, timeframe: str) -> list[Bar]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return read_ohlcv_csv(handle, symbol, timeframe)


def read_ohlcv_csv(
    handle: TextIO, symbol: str, timeframe: str, *,
    interval: timedelta | None = None, max_rows: int | None = None,
) -> list[Bar]:
    reader = csv.DictReader(handle)
    rows: list[Bar] = []
    for item in reader:
        if max_rows is not None and len(rows) >= max_rows:
            raise ValueError(f"CSV exceeds {max_rows} bars")
        try:
            open_time = _parse_timestamp(item["timestamp"])
            if interval is not None and not item.get("close_time"):
                close_time = open_time + interval - timedelta(microseconds=1)
            else:
                close_time = _parse_timestamp(item.get("close_time", item["timestamp"]))
            trade_count = float(item.get("trades", 0))
            if interval is not None and (not trade_count.is_integer() or trade_count < 0):
                raise ValueError("trades must be a nonnegative integer")
            rows.append(Bar(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
                quote_volume=float(item.get("quote_volume", 0.0)),
                trades=int(trade_count),
                is_closed=True,
                source="csv",
            ))
        except (KeyError, TypeError, ValueError, AttributeError, OSError, OverflowError) as exc:
            raise ValueError(f"invalid OHLCV values at CSV line {reader.line_num}") from exc
    return rows
