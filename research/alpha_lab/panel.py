"""Panel ingestion and a deterministic generated fixture."""
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd


def synthetic(days=300, assets=16, seed=42):
    if min(days, assets) < 3:
        raise ValueError("at least three days and assets required")
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, .012, (days, assets)) + rng.normal(0, .003, (days, 1))
    close = 100 * np.exp(np.cumsum(returns, axis=0))
    dates = pd.bdate_range("2024-01-01", periods=days)
    return pd.DataFrame({"date": np.repeat(dates.strftime("%Y-%m-%d"), assets),
                         "asset": np.tile([f"SYN{i:02d}" for i in range(assets)], days),
                         "close": close.ravel(),
                         "volume": rng.lognormal(10, .3, (days, assets)).ravel()})


def validate(frame):
    required = {"date", "asset", "close", "volume"}
    if set(frame.columns) != required:
        raise ValueError("panel columns must be exactly date, asset, close, volume")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].isna().any() or frame["asset"].isna().any() or not frame["asset"].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
        raise ValueError("date and asset identifiers must be present")
    if frame.duplicated(["date", "asset"]).any():
        raise ValueError("duplicate date/asset rows")
    for name in ("close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")
        if not np.isfinite(frame[name]).all() or (frame[name] <= 0).any():
            raise ValueError(f"{name} must be finite and positive")
    fields = {name: frame.pivot(index="date", columns="asset", values=name).sort_index()
              for name in ("close", "volume")}
    if min(fields["close"].shape) < 3 or fields["close"].isna().any().any():
        raise ValueError("demo runner requires a complete fixed-universe panel")
    return fields


def read(path):
    path = Path(path)
    return validate(pd.read_csv(path)), hashlib.sha256(path.read_bytes()).hexdigest()
