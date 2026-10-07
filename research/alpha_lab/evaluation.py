"""Chronological factor evaluation with delayed, close-to-close holdings."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def weights(signal):
    # Equal gross exposure, dollar-neutral whenever at least three signals
    # exist. Missing values stay out of the portfolio; no forward filling.
    centered = signal.sub(signal.mean(axis=1), axis=0)
    centered = centered.where(signal.count(axis=1) >= 3)
    gross = centered.abs().sum(axis=1)
    return centered.div(gross.where(gross > 1e-12), axis=0).fillna(0)


def portfolio(signal, close, cost_bps=5.0):
    if not np.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("cost_bps must be finite and nonnegative")
    if not signal.index.equals(close.index) or not signal.columns.equals(close.columns):
        raise ValueError("signal and prices must have identical axes")
    target = weights(signal)
    # Signal formed at close t-2 is executed at close t-1 and earns return
    # from close t-1 to close t. This adds an execution bar after observation.
    held = target.shift(2).fillna(0)
    realized = close.pct_change(fill_method=None).fillna(0)
    # Compare new holdings against previous holdings drifted by the return
    # they actually earned. P&L is not compounded into a cash balance model.
    prior = held.shift(1).fillna(0)
    prior_nav = 1 + (prior * realized.shift(1).fillna(0)).sum(axis=1)
    if (prior_nav <= 0).any():
        raise ValueError("portfolio exhausted under the simple drift model")
    drifted = prior.mul(1 + realized.shift(1).fillna(0)).div(prior_nav, axis=0)
    traded = (held - drifted).abs().sum(axis=1)
    gross = (held * realized).sum(axis=1)
    return pd.DataFrame({"gross_return": gross, "turnover": traded,
                         "net_return": gross - traded * cost_bps / 10000})


def metrics(returns):
    net = returns["net_return"]
    sd = net.std(ddof=1)
    equity = (1 + net).cumprod()
    if (net <= -1).any():
        raise ValueError("return below -100%; cannot compound")
    peak = equity.cummax().clip(lower=1)
    return {"days": len(net), "net_return": float(equity.iloc[-1] - 1),
            "sharpe_252": float(net.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
            "max_drawdown": float(-(equity / peak - 1).min()),
            "mean_turnover": float(returns["turnover"].mean())}


def evaluate(signal, close, train_fraction=.6, cost_bps=5.0):
    if not .2 <= train_fraction <= .8 or len(close) < 40:
        raise ValueError("need at least 40 dates and train_fraction in [.2, .8]")
    cut = int(len(close) * train_fraction)
    # Signal-date labels reflect the same observation/execution convention:
    # signal at t, execution at close t+1, outcome at close t+2.
    future = close.shift(-2) / close.shift(-1) - 1
    valid_count = (signal.notna() & future.notna()).sum(axis=1)
    ic = signal.rank(axis=1).corrwith(future.rank(axis=1), axis=1).where(valid_count >= 3)
    result = portfolio(signal, close, cost_bps)
    split = {"train": result.iloc[:cut], "holdout": result.iloc[cut:]}
    # Purge the final two train signal dates so no label crosses the boundary.
    ic_splits = {"train": ic.iloc[:cut - 2], "holdout": ic.iloc[cut:]}
    summary = {}
    for name, segment in split.items():
        summary[name] = metrics(segment)
        summary[name]["rank_ic"] = float(ic_splits[name].mean()) if ic_splits[name].notna().any() else None
        summary[name]["ic_dates"] = int(ic_splits[name].notna().sum())
    return summary, result


def correlation(signals):
    # A local signal-correlation diagnostic; not any platform's proprietary
    # self-correlation, production-correlation, or originality measure.
    if not signals:
        return pd.DataFrame()
    vectors = {name: value.stack().rename(name) for name, value in signals.items()}
    return pd.DataFrame(vectors).corr(method="spearman")
