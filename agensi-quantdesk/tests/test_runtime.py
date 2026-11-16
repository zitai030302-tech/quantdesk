"""Offline acceptance tests against a wheel and a single staged Agensi script."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

from quantdesk_agensi_runtime import cli, research
from quantdesk_agensi_runtime.core.backtest.broker import BacktestBroker
from quantdesk_agensi_runtime.core.backtest.metrics import max_drawdown, sharpe_ratio, win_rate
from quantdesk_agensi_runtime.core.data.models import Bar


def bar(i, opening, high, low, close):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
    return Bar("BTC/USDT", "1h", start, start + timedelta(minutes=59), opening, high, low, close, 1)


class BrokerMath(unittest.TestCase):
    def test_next_open_fees_slippage_and_net_pnl(self):
        broker = BacktestBroker(1000, 0.01, 100)
        now = bar(0, 100, 101, 99, 100)
        broker.queue_entry(now.symbol, now.close_time, 2, 80, 140, "entry")
        self.assertEqual(broker.trades, [])
        following = bar(1, 100, 109, 90, 105)
        broker.process_bar(following)
        trade = broker.trades[0]
        self.assertEqual(trade.entry_time, following.open_time)
        self.assertAlmostEqual(trade.entry_price, 101)
        self.assertAlmostEqual(trade.fee, 2.02)
        self.assertAlmostEqual(broker.equity_curve[-1], 1005.98)
        broker.queue_exit(following.close_time, "signal exit")
        broker.process_bar(bar(2, 110, 150, 70, 100))
        self.assertAlmostEqual(trade.exit_price, 108.9)
        self.assertAlmostEqual(trade.exit_fee, 2.178)
        self.assertAlmostEqual(trade.slippage_cost, 4.2)
        self.assertAlmostEqual(trade.pnl, 11.602)
        self.assertAlmostEqual(broker.cash, 1011.602)
        self.assertEqual(trade.exit_reason, "signal exit")
        self.assertEqual(trade.exit_time, bar(2, 110, 150, 70, 100).open_time)

    def test_stop_gap_uses_open(self):
        broker = BacktestBroker(1000, 0)
        broker.queue_entry("BTC/USDT", bar(0, 100, 101, 99, 100).close_time, 2, 90, 110, "entry")
        broker.process_bar(bar(1, 100, 109, 91, 100))
        broker.process_bar(bar(2, 80, 115, 75, 100))
        self.assertEqual(broker.trades[0].exit_price, 80)
        self.assertEqual(broker.trades[0].exit_reason, "stop_loss")

    def test_stop_first_when_both_levels_touched_intrabar(self):
        broker = BacktestBroker(1000, 0)
        broker.queue_entry("BTC/USDT", bar(0, 100, 101, 99, 100).close_time, 2, 90, 110, "entry")
        broker.process_bar(bar(1, 100, 115, 80, 102))
        self.assertEqual(broker.trades[0].exit_price, 90)
        self.assertEqual(broker.trades[0].exit_time, bar(1, 100, 115, 80, 102).close_time)

    def test_gap_entry_cash_or_bracket_rejection(self):
        for cash, opening in [(100, 110), (1000, 79), (1000, 150)]:
            with self.subTest(cash=cash, opening=opening):
                broker = BacktestBroker(cash, 0)
                broker.queue_entry("BTC/USDT", bar(0, 100, 101, 99, 100).close_time, 1, 80, 140, "entry")
                broker.process_bar(bar(1, opening, opening, opening, opening))
                self.assertEqual(broker.trades, [])
                self.assertIsNone(broker.pending_entry)

    def test_historical_risk_day_rolls_between_samples(self):
        from quantdesk_agensi_runtime.core.app.types import RiskConfig, RuntimeMode
        from quantdesk_agensi_runtime.core.data.models import AccountSnapshot, FillRecord, Side
        from quantdesk_agensi_runtime.core.risk.manager import RiskManager

        manager = RiskManager(RiskConfig(), RuntimeMode.BACKTEST)
        today = bar(23, 100, 101, 99, 100).close_time
        tomorrow = bar(24, 100, 101, 99, 100).open_time
        manager.observe_account(AccountSnapshot(today, {}, 1000, 1000))
        manager.on_trade_closed(FillRecord("fill", "order", "BTCUSDT", Side.SELL, 1, 99, 1, "USDT", -5, today))
        self.assertEqual(manager.state.realized_pnl, -5)
        manager.observe_account(AccountSnapshot(tomorrow, {}, 995, 995))
        self.assertEqual(manager.state.trade_date, tomorrow.date())
        self.assertEqual(manager.state.realized_pnl, 0)
        self.assertEqual(manager.state.starting_nav, 995)

    def test_metrics_against_hand_calculation(self):
        equity = [100.0, 110.0, 99.0, 99.0]
        self.assertAlmostEqual(max_drawdown(equity), 0.1)
        self.assertEqual(win_rate([20, -2, 0]), 1 / 3)
        self.assertAlmostEqual(sharpe_ratio([0.1, -0.1, 0], 4), 0)
        from types import SimpleNamespace

        metrics = research.metrics(SimpleNamespace(trades=[], total_return=-0.01, max_drawdown=0.1, sharpe=0, win_rate=0),
                                   equity, 4, 3 * 3600)
        self.assertAlmostEqual(metrics["sortino_ratio"], 0)
        self.assertIsNone(metrics["annualized_return"])
        self.assertIsNone(metrics["win_rate"])
        self.assertEqual(metrics["transaction_costs"], 0)
        self.assertAlmostEqual(math.sqrt((0 + .01 + 0) / 3), .1 / math.sqrt(3))


class InstalledZip(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="QuantDesk 测试 ")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.work = self.directory / "work dir"
        self.work.mkdir()
        script_dir = self.directory / "script alone"
        script_dir.mkdir()
        self.script = script_dir / "quantdesk.py"
        with zipfile.ZipFile(ZIP) as package:
            self.script.write_bytes(package.read("scripts/quantdesk.py"))
            self.data = package.read("examples/btc_synthetic_1h.csv")
            self.requests = {name: json.loads(package.read(f"templates/{name}-request.json"))
                             for name in ("research", "paper")}

    def command(self, *args, fail=False):
        result = subprocess.run([sys.executable, "-I", str(self.script), *map(str, args)],
                                cwd=self.work, text=True, encoding="utf-8", capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 2 if fail else 0, result.stdout + result.stderr)
        return result

    def request(self, name, payload):
        path = self.work / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def custom(self, mode, raw, request=None, name="out", fail=False):
        path = self.work / "fixture file.csv"
        path.write_bytes(raw)
        params = self.request("request file.json", self.requests["research"] if request is None else request)
        return self.command(mode, "--request", params, "--csv", path, "--output", name, fail=fail)

    def load(self, name):
        return json.loads(self.work.joinpath(name, "result.json").read_text(encoding="utf-8"))

    def test_doctor_detached(self):
        result = json.loads(self.command("doctor").stdout)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["runtime"], "0.1.0")
        self.assertTrue(result["offline"])
        self.assertRegex(result["source_sha256"], r"^[0-9a-f]{64}$")

    def test_minimal_backtest_outputs(self):
        self.command("backtest", "--demo", "--output", "one run")
        report = self.load("one run")
        out = self.work / "one run"
        self.assertEqual({x.name for x in out.iterdir()},
                         {"result.json", "report.md", "metrics.csv", "trades.csv", "equity.csv"})
        self.assertGreater(report["runs"][0]["metrics"]["trade_count"], 0)
        self.assertEqual(report["data"]["bars"], 160)
        with (out / "metrics.csv").open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertAlmostEqual(float(row["transaction_costs"]), report["runs"][0]["metrics"]["transaction_costs"])
        self.assertIn("CSV SHA-256", (out / "report.md").read_text(encoding="utf-8"))

    def test_comparison_balanced_exact_equivalence(self):
        self.command("compare", "--demo", "--output", "compared")
        self.command("backtest", "--demo", "--output", "one")
        compared = self.load("compared")
        individual = self.load("one")
        self.assertEqual(compared["runs"][0], individual["runs"][0])
        self.assertEqual(compared["data"], individual["data"])
        self.assertEqual(len(compared["runs"]), 2)
        self.assertNotEqual(compared["runs"][0]["metrics"], compared["runs"][1]["metrics"])

    def test_reproducible_research_reports(self):
        self.command("backtest", "--demo", "--output", "repeat 1")
        self.command("backtest", "--demo", "--output", "repeat 2")
        for first in (self.work / "repeat 1").iterdir():
            self.assertEqual(first.read_bytes(), (self.work / "repeat 2" / first.name).read_bytes())

    def test_prefix_causality_future_ohlc_cannot_change_previous_equity(self):
        rows = self.data.splitlines(keepends=True)
        self.custom("backtest", b"".join(rows[:81]), name="prefix")
        self.custom("backtest", self.data, name="full")
        def curve(name):
            with self.work.joinpath(name, "equity.csv").open(encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))
        self.assertEqual(curve("prefix"), curve("full")[:81])

    def test_invalid_csv_gaps_order_duplicates_nonfinite_ohlc(self):
        lines = self.data.decode().splitlines()
        for case, rows in {
            "gap": lines[:13] + lines[14:],
            "duplicate": lines[:13] + [lines[12]] + lines[13:],
            "out of order": [lines[0], lines[2], lines[1], *lines[3:]],
            "extra field": [lines[0], lines[1] + ",x", *lines[2:]],
            "nonfinite": [lines[0], lines[1].replace(",100,", ",nan,", 1), *lines[2:]],
            "inconsistent": [lines[0], lines[1].replace(",101,", ",50,", 1), *lines[2:]],
            "too short": lines[:3],
        }.items():
            with self.subTest(case=case):
                self.custom("backtest", ("\n".join(rows) + "\n").encode(), fail=True)
                self.assertFalse((self.work / "out").exists())

    def test_invalid_schema_and_live_command(self):
        wrong = self.requests["research"] | {"live": True}
        self.custom("backtest", self.data, request=wrong, fail=True)
        wrong = self.requests["research"] | {"strategies": [{"name": "ema_trend", "parameters": {"fast_period": 21}}]}
        self.custom("backtest", self.data, request=wrong, fail=True)
        self.command("live", fail=True)
        self.command("paper", "--demo", "--csv", "unused", "--output", "out", fail=True)
        self.assertFalse((self.work / "out").exists())

    def test_missing_metrics_are_explicit(self):
        records = list(csv.DictReader(io.StringIO(self.data.decode())))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows((row["timestamp"], 100, 101, 99, 100, 5) for row in records)
        self.custom("backtest", output.getvalue().encode())
        values = self.load("out")["runs"][0]["metrics"]
        for key in ("sharpe_ratio", "sortino_ratio", "annualized_return", "win_rate"):
            self.assertIsNone(values[key])
        self.assertEqual(values["trade_count"], 0)

    def test_paper_runtime_uses_no_network_or_child_process(self):
        # Asyncio may create a local loopback socket pair on Windows.
        harness = """
import runpy, sys
def guard(event, args):
    if event in {"socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise AssertionError(event)
    if event in {"socket.connect", "socket.bind", "socket.sendto"}:
        address = args[-1]
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError(event)
sys.addaudithook(guard)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
        result = subprocess.run([sys.executable, "-I", "-c", harness, str(self.script),
                                 "paper", "--demo", "--output", "sandbox paper"], cwd=self.work,
                                text=True, encoding="utf-8", capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_output_preserved(self):
        self.command("paper", "--demo", "--output", "paper account")
        original = (self.work / "paper account" / "paper.sqlite3").read_bytes()
        self.command("paper", "--demo", "--output", "paper account", fail=True)
        self.assertEqual(original, (self.work / "paper account" / "paper.sqlite3").read_bytes())

    def test_paper_cost_exposure_inventory_and_sqlite(self):
        self.command("paper", "--demo", "--output", "paper")
        report = self.load("paper")
        self.assertEqual((report["filled"], report["rejected"]), (2, 2))
        self.assertIn("max_position_value", report["events"][1]["reasons"])
        self.assertIn("insufficient_inventory", report["events"][2]["reasons"])
        self.assertAlmostEqual(report["ending_cash"], 954.7674775)
        self.assertAlmostEqual(report["ending_equity"], 1009.7674775)
        self.assertEqual(report["position_quantity"], 0.5)
        connection = sqlite3.connect(self.work / "paper" / "paper.sqlite3")
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT mode, COUNT(*) FROM orders GROUP BY mode").fetchall(), [("paper", 2)])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone(), (2,))
            self.assertEqual(connection.execute("SELECT quantity FROM positions").fetchone(), (0.5,))
            ledger = json.loads(connection.execute("SELECT report_json FROM paper_scenario").fetchone()[0])
            self.assertEqual(ledger["events"], report["events"])
        finally:
            connection.close()

    def test_paper_insufficient_cash_and_repeatability(self):
        request = self.requests["paper"] | {"initial_cash": 100, "max_position_value": 1000}
        path = self.request("paper.json", request)
        self.command("paper", "--request", path, "--output", "a")
        self.command("paper", "--request", path, "--output", "b")
        first = self.load("a")
        self.assertEqual(first, self.load("b"))
        self.assertEqual(first["filled"], 0)
        self.assertEqual(first["rejected"], 4)
        self.assertEqual(first["ending_cash"], 100)


if __name__ == "__main__":
    ZIP = Path(sys.argv.pop(1)).resolve(strict=True)
    unittest.main(verbosity=2)
