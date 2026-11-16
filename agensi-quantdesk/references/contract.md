# Input and output contract

Use `templates/research-request.json` and `templates/paper-request.json` to
start. JSON must use UTF-8 with unique keys. Unknown fields produce an error.

## Backtest and comparison

The required keys are `symbol`, `timeframe`, and `strategies`. Use uppercase
`BASE/USDT`, `BASE/USD`, or `BASE/USDC` for a crypto spot series. Supported
intervals are `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, and `1w`.
Each item in `strategies` has a `name` and optional `parameters`. Use one
configuration for a backtest and two to six distinct configurations for a
comparison. All runs share the CSV, cash, risk limit and costs.

| Strategy | Default parameters |
| --- | --- |
| `ema_trend` | `fast_period=9`, `slow_period=21`, `atr_period=14`, `min_trend_strength=0` |
| `rsi_bbands_mean_reversion` | `rsi_period=14`, `bb_period=20`, `bb_stddev=2`, `rsi_oversold=28`, `rsi_overbought=72`, `exit_at_midline=true` |

Periods are integers from 2 to 240. Fast EMA must be shorter than slow.
Trend strength is a fraction from 0 to 1. Bollinger deviation is 0.1 to 10.
RSI thresholds are ordered within 0 to 100. Minimum sample is the largest
strategy or risk warmup period plus two bars. Strategy ATR and the risk
manager's fixed 14-bar ATR are separate.

Optional run inputs are `initial_cash` (defaults to 10000 quote units),
`fee_bps` (10), `slippage_bps` (5), `risk_per_trade` (0.005 of equity), and
`data_source` (short plain-text provenance label).

CSV requires `timestamp,open,high,low,close,volume`. Optional columns are
`close_time,quote_volume,trades`. Timestamps are ISO 8601 or Unix seconds
or milliseconds. Offsetless ISO inputs are interpreted as UTC. If omitted,
close time is interval end minus one microsecond. An explicit close time
must be after bar open and before the next scheduled bar open. All rows
must be consecutive, fully closed, ordered and unique. Use a single
instrument per CSV and supply your venue, date window and source label.
The parser verifies structure and timestamps. It cannot verify whether a
provider's input was point-in-time or an unfinished candle. Limits are
2,000 bars and 2 MB per CSV. JSON is capped at 128 KB.

## Paper

Supply `symbol`, `max_position_value` in quote units, and `orders` with
one to 100 intents. Each has `side` (`buy` or `sell`), `quantity` in base
units, and `price` as its simulated reference price. Initial cash and
cost defaults match research. The scenario starts with virtual cash and
processes the intents in order. It records fills and rejections. Each
invocation starts a separate virtual account. The resulting database is a
persistent audit ledger for that run.

## Reports and errors

On success, stdout prints a JSON envelope with `status: ok` and the report
folder. Read `result.json` for structured results and `report.md` for a
human-readable table, inputs, settings and environment. Research writes
`metrics.csv`, `equity.csv`, and `trades.csv`. Paper writes `paper.csv`
and `paper.sqlite3` with one run's records. Costs are in quote units.
Ratios and returns use decimal fractions except Sharpe and Sortino, which
are dimensionless. Optional metrics missing their denominator or required
coverage are JSON `null`, blank CSV fields and “unavailable” in Markdown.

Exit status 2 means bad input, missing runtime, filesystem failure, or
invalid arguments. Read stderr. Correct the input and retry with a fresh
output directory. Run `doctor` before invoking a workflow.
