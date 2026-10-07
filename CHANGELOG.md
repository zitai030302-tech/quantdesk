# Changes

## 2026-10-08

- Fixed backtest Sharpe annualization to use the requested bar interval instead of always assuming one-minute bars.
- Added an offline factor-research module with restricted expressions, chronological evaluation, signal-correlation inspection, and a SQLite experiment ledger.
- Added a sample-backtest Docker entry point. The default container command uses a checked-in CSV.
- Added research tests for signal causality, execution timing, train/holdout separation, transaction costs, malformed data, and experiment identity.

The generated panel is a pipeline fixture. It is not evidence of strategy performance on a market.
