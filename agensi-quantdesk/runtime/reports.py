"""Serialize validated results to local research files."""
import csv
import json
from pathlib import Path


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def write(output: Path, report, tables):
    output.joinpath("result.json").write_text(json_text(report), encoding="utf-8")
    for name, (columns, rows) in tables.items():
        with output.joinpath(f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, columns)
            writer.writeheader()
            writer.writerows(rows)
    if report["mode"] == "paper":
        lines = [
            "# QuantDesk paper risk check", "",
            f"Virtual fills: {report['filled']}. Rejected intents: {report['rejected']}.",
            f"Ending cash: {report['ending_cash']:.8g}. Ending equity: {report['ending_equity']:.8g}.",
            f"Ending position: {report['position_quantity']:.8g}. Fees: {report['total_fees']:.8g}.",
            f"Scenario SHA-256 `{report['request_sha256']}`.",
            "The SQLite ledger stores this scenario's orders, fills, final position and risk decisions.",
        ]
    else:
        data = report["data"]
        lines = [
            f"# QuantDesk {report['mode']}", "",
            f"{data['symbol']} · {data['timeframe']} · {data['bars']} bars · {data['source']}",
            f"From {data['start']} through {data['last_close']}.",
            f"CSV SHA-256 `{data['sha256']}`.", "",
            f"Costs in {data['quote_asset']}. Returns, drawdown, win rate and turnover are decimal fractions.",
            "", "| Run | Strategy | Return | Annualized | Sharpe | Sortino | Max drawdown | Win rate | Closed trades | Fees | Slippage | Total costs | Turnover |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for run in report["runs"]:
            values = run["metrics"]
            keys = ("total_return", "annualized_return", "sharpe_ratio", "sortino_ratio", "maximum_drawdown",
                    "win_rate", "trade_count", "fees", "slippage_cost", "transaction_costs", "turnover")
            cells = ["unavailable" if values[key] is None else f"{values[key]:.8g}" for key in keys]
            lines.append("| " + " | ".join([str(run["run"]), run["strategy"], *cells]) + " |")
        lines.extend(["", "Signals use closed bars. Orders use the next open; intrabar protection uses OHLC assumptions.",
                      "Open trades remain marked to the last close. Short windows and sparse trades limit inference."])
        parameters = [{"run": run["run"], "strategy": run["strategy"], **run["parameters"]} for run in report["runs"]]
        lines.extend(["", "## Strategy parameters", "", "```json", json_text(parameters).strip(), "```"])
    lines.extend(["", "## Run settings", "", "```json", json_text(report["assumptions"]).strip(), "```",
                  "", "## Reproduce", "",
                  f"Use the same inputs and settings with the `{report['mode']}` command and a new output directory.",
                  f"Runtime {report['environment']['runtime']}, Python {report['environment']['python']}, "
                  f"{report['environment']['system']} {report['environment']['machine']}.",
                  "Research simulation. Results depend on data quality and execution assumptions.", ""])
    output.joinpath("report.md").write_text("\n".join(lines), encoding="utf-8")
