# AlphaResearchLab

A local factor-research loop: write a hypothesis, validate an expression, evaluate it, inspect correlation, and keep the experiment record.

This starts with four simple baselines and generated price/volume panels. It is kept as a separate research module in QuantDesk while the interface settles. It has no dependency on trading credentials or WorldQuant data.

## Run

From the QuantDesk repository root:

```bash
python -m pip install -r requirements-research.txt
python -m research.alpha_lab --synthetic --output /tmp/alpha-demo
cat /tmp/alpha-demo/report.md
```

For local daily data, use `--panel panel.csv` instead of `--synthetic`. The CSV must contain exactly `date,asset,close,volume`, one row per date and asset, positive numeric values, and a complete fixed universe. The runner deliberately rejects missing observations rather than silently filling prices.

## What is implemented

- a restricted expression tree: `rank`, `delay`, `delta`, `ts_mean`, `ts_std`, `neg`, `abs`, `add`, `sub`, `mul`, `div`
- cross-sectional, dollar-neutral, unit-gross target weights
- delayed close-to-close execution and turnover costs
- a chronological development/holdout split, with boundary-purged train IC labels
- rank IC, Sharpe, drawdown, turnover, and development-only signal correlation
- expression fingerprints and a SQLite ledger with explicit failed experiments
- input/config/source hashes and per-factor return CSVs

The timing convention is conservative: a signal observed at close t trades at close t+1 and earns the t+1 to t+2 return. The cost model compares target positions with holdings drifted by realized returns. It omits borrow fees, impact, and short-sale constraints.

## Where a model can help

An external model can propose JSON objects matching `examples/proposals.json`. The runner accepts only the typed `name`, `hypothesis`, and `expression` fields. It never evaluates Python supplied by the model. The same validation, split, and ledger apply to handwritten and model-proposed candidates.

There is currently no live LLM loop, automatic platform submission, or claimed WorldQuant API integration. The public module contains no platform alpha, account data, or private research receipts. Its local correlation measure is not WorldQuant's originality score.

## Next experiments

1. Add a public-data adapter with adjustment and universe provenance.
2. Freeze a candidate batch before inspecting a fresh holdout interval.
3. Compare turnover and costs before changing the proposal policy.
4. Add a model adapter that records its prompt, response, and validation failures.

The generated-data report verifies the pipeline. It says nothing about investment performance.
