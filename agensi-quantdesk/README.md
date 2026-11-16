# QuantDesk Agensi Skill 0.1.0

Run a local crypto OHLCV backtest, compare up to six configurations, or simulate
virtual orders against cash, inventory and position limits. The research
workflows call the original QuantDesk engine and strategy registry. The paper
workflow uses QuantDesk's local PaperBroker, order validator and SQLite
repositories.

## Install and run

Use a dedicated Python 3.11+ virtual environment. The universal
`quantdesk_agensi_runtime-0.1.0-py3-none-any.whl` is a separate first-party
distribution file. For this review release, obtain it and its SHA-256 from
the QuantDesk delivery folder or the publisher. Install the verified wheel
locally. No provider package, account or key is needed. The packaged Agensi
script can run from any temporary directory after this installation.

```text
python -m venv .qd-venv
```

Use `.qd-venv/bin/python` on macOS/Linux and
`.qd-venv\Scripts\python.exe` on Windows in place of `<env-python>` below.
The example paths are relative to an extracted author-review copy of the ZIP.

```text
<env-python> -I -m pip install --no-index --no-deps "quantdesk_agensi_runtime-0.1.0-py3-none-any.whl"
<env-python> -I "scripts/quantdesk.py" doctor
<env-python> -I "scripts/quantdesk.py" backtest --demo --output "qd-backtest"
<env-python> -I "scripts/quantdesk.py" compare --demo --output "qd-compare"
<env-python> -I "scripts/quantdesk.py" paper --demo --output "qd-paper"
```

Use a new output directory for every run. `--demo` uses synthetic inputs.
See [the request and output contract](references/contract.md) for your data
and [the execution methodology](references/methodology.md) for fill, cost and
risk definitions. Runtime version and source hash are available from `doctor`
and recorded in reports.

## Future roadmap

Exchange calendars and corporate-action handling for stocks and ETFs,
multi-asset work, purpose-built factor experiments, and explicitly authorized
optional data tools. For 0.1.0, workflows consume local files and simulated
order intents only.

The QuantDesk source subset retains its MIT notices in the wheel.
