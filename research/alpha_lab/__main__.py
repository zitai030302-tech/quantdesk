"""Offline proposals -> expressions -> evaluation -> correlation -> ledger."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from .evaluation import correlation, evaluate
from .expressions import Proposal, compute, fingerprint
from .ledger import Ledger
from .panel import read, synthetic


def code_hash():
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def run(panel_path, proposals_path, output, train_fraction=.6, cost_bps=5.0):
    fields, data_hash = read(panel_path)
    candidates = json.loads(Path(proposals_path).read_text())
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
        raise ValueError("proposal file must contain 1–100 candidates")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    config = {"data_sha256": data_hash, "source_sha256": code_hash(),
              "train_fraction": train_fraction, "cost_bps": cost_bps,
              "signal_to_return_bars": 2, "periods_per_year": 252,
              "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}
    ledger = Ledger(output / "experiments.sqlite")
    results, signals, seen = [], {}, set()
    for i, item in enumerate(candidates):
        receipt = None
        try:
            proposal = Proposal.from_dict(item)
            identity = fingerprint(proposal.expression)
            if proposal.name in signals:
                raise ValueError("duplicate proposal name")
            if identity in seen:
                results.append({"name": proposal.name, "status": "duplicate_expression", "fingerprint": identity})
                continue
            seen.add(identity)
            signal = compute(proposal.expression, fields)
            # Do not report an untradeable factor as a successful zero-P&L run.
            if (signal.count(axis=1) >= 3).sum() < 20 or not (signal.std(axis=1) > 1e-12).any():
                raise ValueError("insufficient nonconstant cross-sectional signal")
            summary, returns = evaluate(signal, fields["close"], train_fraction, cost_bps)
            receipt = ledger.record(asdict(proposal), config, "completed", summary)
            returns.to_csv(output / f"returns_{identity[:12]}.csv", index_label="date")
            # Correlation is assessed only on the development segment.
            signals[proposal.name] = signal.iloc[:int(len(signal) * train_fraction)]
            results.append({"name": proposal.name, "expression": proposal.expression,
                            "fingerprint": identity, "status": "completed", "metrics": summary, "receipt": receipt})
        except (ValueError, KeyError, TypeError) as exc:
            stored = item if isinstance(item, dict) else {"invalid_candidate": item}
            receipt = ledger.record(stored, config, "failed", error=str(exc))
            results.append({"candidate_index": i, "status": "failed", "error": str(exc), "receipt": receipt})
    (output / "results.json").write_text(json.dumps({"config": config, "results": results}, indent=2, allow_nan=False) + "\n")
    correlation(signals).to_csv(output / "development_signal_correlation.csv")
    lines = ["# Local factor experiment", "", "Generated/local data; these results are not WorldQuant platform metrics.", "", "| Factor | Train rank IC | Holdout rank IC | Holdout Sharpe (252) | Holdout drawdown |", "|---|---:|---:|---:|---:|"]
    for r in results:
        if r["status"] == "completed":
            tr, ho = r["metrics"]["train"], r["metrics"]["holdout"]
            fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
            lines.append(f"| {r['name']} | {fmt(tr['rank_ic'])} | {fmt(ho['rank_ic'])} | {ho['sharpe_252']:.3f} | {ho['max_drawdown']:.2%} |")
        else:
            lines.append(f"\nCandidate {r.get('name', r.get('candidate_index'))}: {r['status']} {r.get('error', '')}")
    lines.extend(["", "The split and candidate list are fixed before evaluation. Development correlation does not inspect holdout dates. No candidate is automatically selected using holdout performance.", "", "Signals are observed at close t, executed at close t+1, and earn close t+1 to t+2 returns. Transaction cost is charged on changes from drifted holdings. Short financing, market impact, and borrow availability are not modeled."])
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel")
    parser.add_argument("--proposals", default=str(Path(__file__).parent / "examples/proposals.json"))
    parser.add_argument("--output", default="research/alpha_lab/output")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cost-bps", type=float, default=5)
    args = parser.parse_args()
    if bool(args.panel) == bool(args.synthetic):
        parser.error("choose exactly one of --panel or --synthetic")
    panel_path = args.panel
    if args.synthetic:
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        panel_path = output / "synthetic_panel.csv"
        synthetic(seed=args.seed).to_csv(panel_path, index=False)
    results = run(panel_path, args.proposals, args.output, cost_bps=args.cost_bps)
    print(f"{sum(r['status'] == 'completed' for r in results)}/{len(results)} factors completed; {args.output}/report.md")
    if any(r["status"] == "failed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
