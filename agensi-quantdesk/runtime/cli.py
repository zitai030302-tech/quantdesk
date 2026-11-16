"""Explicit invocation boundary shared by the Skill and local CLI."""
from __future__ import annotations

import argparse
import asyncio
import csv
from contextlib import closing
import hashlib
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import __version__, paper, reports, research
from .inputs import read_request

DEMO_RESEARCH = {"symbol": "BTC/USDT", "timeframe": "1h", "data_source": "Synthetic BTC fixture",
                 "strategies": [{"name": "ema_trend", "parameters": {"fast_period": 3, "slow_period": 7}}]}
DEMO_PAPER = {"symbol": "BTC/USDT", "initial_cash": 1000, "max_position_value": 300,
              "fee_bps": 10, "slippage_bps": 5, "orders": [
                  {"side": "buy", "quantity": 1, "price": 100},
                  {"side": "buy", "quantity": 3, "price": 100},
                  {"side": "sell", "quantity": 2, "price": 110},
                  {"side": "sell", "quantity": 0.5, "price": 110},
              ]}


def environment():
    source_hash = Path(__file__).with_name("source.sha256").read_text(encoding="ascii").strip()
    return {"runtime": __version__, "python": platform.python_version(), "system": platform.system(),
            "machine": platform.machine(), "sqlite": sqlite3.sqlite_version, "source_sha256": source_hash}


def run(args):
    mode = args.command
    if mode == "paper" and args.csv:
        raise ValueError("paper uses order intents, so omit --csv")
    if mode != "paper" and bool(args.csv) == args.demo:
        raise ValueError("supply --csv with --request, or use --demo on its own")
    request = read_request(args.request) if args.request else None
    parent = args.output.parent.resolve()
    destination = parent / args.output.name
    if destination.exists() or destination.is_symlink() or not destination.name or destination.name in (".", ".."):
        raise ValueError("select a new output directory")
    if not parent.is_dir():
        raise ValueError("output parent must already be a local directory")

    with tempfile.TemporaryDirectory(prefix=".quantdesk-", dir=parent) as temporary:
        stage = Path(temporary)
        if mode == "paper":
            report, tables = asyncio.run(paper.run(DEMO_PAPER if args.demo else request, stage))
        elif args.demo:
            request = dict(DEMO_RESEARCH)
            if mode == "compare":
                request["strategies"] = [*request["strategies"], {"name": "rsi_bbands_mean_reversion"}]
            fixture = Path(__file__).with_name("btc_synthetic_1h.csv")
            report, tables = research.run(request, fixture, mode)
        else:
            report, tables = research.run(request, args.csv, mode)
        report["environment"] = environment()
        reports.write(stage, report, tables)
        # Reserve a new directory before moving any files. No existing output can be overwritten.
        destination.mkdir()
        written = []
        try:
            for artifact in sorted(stage.iterdir()):
                target = destination / artifact.name
                artifact.rename(target)
                written.append(target)
        except OSError:
            for target in written:
                target.unlink()
            destination.rmdir()
            raise
    return {"status": "ok", "mode": mode, "output": str(destination), "report": "result.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="quantdesk-agensi", description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="Check the installed offline runtime")
    for name, help_text in (("backtest", "Run one strategy"), ("compare", "Compare two to six strategies"),
                            ("paper", "Simulate bounded virtual orders and save a SQLite ledger")):
        command = subcommands.add_parser(name, help=help_text)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--request", type=Path, help="Local JSON request")
        source.add_argument("--demo", action="store_true", help="Use the bundled synthetic fixture")
        command.add_argument("--csv", type=Path, help="Local OHLCV CSV for backtest or compare")
        command.add_argument("--output", type=Path, required=True, help="New report directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            with closing(sqlite3.connect(":memory:")) as db:
                db.execute("SELECT 1").fetchone()
            fixture = Path(__file__).with_name("btc_synthetic_1h.csv")
            result = {"status": "ok", **environment(), "offline": True,
                      "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
        else:
            result = run(args)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    except (OSError, OverflowError, ValueError, csv.Error, sqlite3.Error) as exc:
        # OS errors can include private paths; retain its safe description only.
        message = (exc.strerror or type(exc).__name__) if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"status": "error", "message": message}, ensure_ascii=True), file=sys.stderr)
        return 2
    return 0
