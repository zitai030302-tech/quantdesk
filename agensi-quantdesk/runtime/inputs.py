"""Bounded, explicit input contract for the QuantDesk runtime."""
from __future__ import annotations

import csv
from datetime import timedelta
import hashlib
import io
import json
import math
import re
import stat
from pathlib import Path

from .core.app.types import StrategyConfig, StrategyParams
from .core.data.csv_loader import read_ohlcv_csv
from .core.data.models import ExchangeRule

MAX_BARS = 2_000
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
              "4h": 14400, "1d": 86400, "1w": 604800}
STRATEGIES = {
    "ema_trend": {"fast_period": 9, "slow_period": 21, "atr_period": 14, "min_trend_strength": 0.0},
    "rsi_bbands_mean_reversion": {"rsi_period": 14, "bb_period": 20, "bb_stddev": 2.0,
                                  "rsi_oversold": 28, "rsi_overbought": 72, "exit_at_midline": True},
}


def bounded_file(path: Path, maximum: int) -> bytes:
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("input must be a regular local file")
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"input exceeds {maximum} bytes")
    return data


def fields(value, *, allowed, required=(), label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _pairs(items):
    parsed = dict(items)
    if len(parsed) != len(items):
        raise ValueError("duplicate JSON keys")
    return parsed


def read_request(path: Path) -> dict:
    raw = bounded_file(path, 128_000)
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("request must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request must be a JSON object")
    return value


def number(value, lower, upper, label):
    if type(value) not in (int, float) or not lower <= value <= upper:
        raise ValueError(f"{label} must be a number from {lower} to {upper}")
    return float(value)


def symbol_rule(value) -> ExchangeRule:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{2,12}/(?:USDT|USD|USDC)", value):
        raise ValueError("symbol must be uppercase BASE/USDT, BASE/USD or BASE/USDC")
    base, quote = value.split("/")
    if base == quote:
        raise ValueError("base and quote assets must differ")
    return ExchangeRule(value.replace("/", ""), 0.01, 0.000001, 0.000001, 1.0, base, quote)


def read_bars(path: Path, symbol: str, timeframe: str):
    raw = bounded_file(path, 2_000_000)
    interval = timedelta(seconds=TIMEFRAMES[timeframe])
    body = raw.decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(body, newline=""), strict=True), [])
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    optional = {"close_time", "quote_volume", "trades"}
    if not required <= set(header) <= (required | optional) or len(header) != len(set(header)):
        raise ValueError("CSV needs unique OHLCV headers including timestamp")
    # DictReader ignores surplus values. Check physical records before parsing.
    for row_index, row in enumerate(csv.reader(io.StringIO(body, newline=""), strict=True), 1):
        if len(row) != len(header) or (row_index > 1 and any(not item.strip() for item in row)):
            raise ValueError(f"missing or extra CSV fields at record {row_index}")
    bars = read_ohlcv_csv(io.StringIO(body, newline=""), symbol, timeframe,
                          interval=interval, max_rows=MAX_BARS)
    if len(bars) < 2:
        raise ValueError("CSV needs at least two bars")
    for index, bar in enumerate(bars):
        row = index + 2
        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(math.isfinite(p) and 1e-10 <= p <= 1e12 for p in prices):
            raise ValueError(f"OHLC prices must be positive and finite at CSV row {row}")
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError(f"inconsistent OHLC at CSV row {row}")
        if any(not math.isfinite(v) or v < 0 for v in (bar.volume, bar.quote_volume)) or bar.trades < 0:
            raise ValueError(f"invalid volume or trade count at CSV row {row}")
        if not bar.open_time < bar.close_time < bar.open_time + interval:
            raise ValueError(f"close timestamp outside bar at CSV row {row}")
        if index and bar.open_time - bars[index - 1].open_time != interval:
            raise ValueError(f"gap, duplicate or out-of-order timestamp at CSV row {row}")
    return bars, hashlib.sha256(raw).hexdigest()


def strategy_spec(value):
    spec = fields(value, allowed={"name", "parameters"}, required={"name"}, label="strategy")
    name = spec["name"]
    if not isinstance(name, str) or name not in STRATEGIES:
        raise ValueError("strategy must be ema_trend or rsi_bbands_mean_reversion")
    params = STRATEGIES[name] | fields(spec.get("parameters", {}), allowed=STRATEGIES[name], label="parameters")
    for key, val in params.items():
        if key.endswith("_period") and (type(val) is not int or not 2 <= val <= 240):
            raise ValueError(f"{key} must be an integer from 2 to 240")
    if name == "ema_trend":
        if params["fast_period"] >= params["slow_period"]:
            raise ValueError("fast_period must be below slow_period")
        params["min_trend_strength"] = number(params["min_trend_strength"], 0, 1, "min_trend_strength")
    else:
        params["bb_stddev"] = number(params["bb_stddev"], 0.1, 10, "bb_stddev")
        if not (number(params["rsi_oversold"], 0, 100, "rsi_oversold")
                < number(params["rsi_overbought"], 0, 100, "rsi_overbought")):
            raise ValueError("rsi_oversold must be below rsi_overbought")
        if type(params["exit_at_midline"]) is not bool:
            raise ValueError("exit_at_midline must be a Boolean")
    config = StrategyConfig(active_strategy=name)
    setattr(config, name, StrategyParams(params))
    return name, params, config
