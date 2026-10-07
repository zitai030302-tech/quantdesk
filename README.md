# QuantDesk

[![tests](https://github.com/zitai030302-tech/quantdesk/actions/workflows/tests.yml/badge.svg)](https://github.com/zitai030302-tech/quantdesk/actions/workflows/tests.yml)

A Python sandbox for strategy backtests, paper execution, and local factor experiments.

The execution side connects market bars, strategy signals, risk checks, broker adapters, and SQLite records. The research side evaluates candidate factors on local panel data and keeps the experiment configuration with the result.

## Start with local data

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py list-strategies
python main.py backtesting -c config/freqtrade_compat.json --csv tests/fixtures/btcusdt_1m_sample.csv
```

Run these commands from the repository root. The checked-in CSV is a small execution smoke test; it is too short to establish strategy performance and may produce no trades.

For paper trading and dashboard monitoring:

```bash
python main.py trade -c config/freqtrade_compat.json --dry-run --dashboard both
```

That path uses market endpoints. Live trading is disabled in this public version.

## Factor research

[AlphaResearchLab](research/alpha_lab) implements a separate offline loop:

hypothesis → restricted expression → delayed backtest → metrics → correlation → experiment ledger

```bash
python -m pip install -r requirements-research.txt
python -m research.alpha_lab --synthetic --output /tmp/alpha-demo
```

It records failed proposals, source/data hashes, turnover costs, development/holdout metrics, and signal correlations. Model-generated JSON proposals pass through the same validation as handwritten ones. There is no live LLM adapter or WorldQuant submission integration yet.

## Structure

```text
app/          CLI, runtime, and dashboard
backtest/     next-bar broker, metrics, and reports
execution/    broker adapters and order validation
risk/         sizing and protection rules
strategies/   EMA and RSI/Bollinger baselines
data/         market clients and SQLite repositories
research/     offline factor experiments
tests/        unit, integration, and research checks
```

Backtest Sharpe annualization follows the requested fixed bar interval in a 24/7 market. The factor module uses a separate daily-panel convention with 252 periods per year. Neither engine models every exchange or financing detail.

## Verification

```bash
python -m pip install -r requirements-research.txt
python -m pytest -q
```

Tests include paper-engine flow, order validation, risk rules, indicator behavior, failed requests, factor causality, delayed execution, holdout separation, and experiment identity. Network-boundary tests use local fixtures.

To run the CSV smoke test in a container:

```bash
docker build -t quantdesk .
docker run --rm quantdesk
```

The default container command uses the checked-in CSV. CI builds the image and runs that command.

[Changes](CHANGELOG.md) · [License](LICENSE)
