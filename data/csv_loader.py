from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

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
    rows: list[Bar] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            open_time = _parse_timestamp(item["timestamp"])
            close_time = _parse_timestamp(item.get("close_time", item["timestamp"]))
            rows.append(
                Bar(
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
                    trades=int(float(item.get("trades", 0))),
                    is_closed=True,
                    source="csv",
                )
            )
    return rows
