from __future__ import annotations

from pathlib import Path


def save_equity_curve(path: str | Path, timestamps: list[str], equity_curve: list[float]) -> Path:
    import matplotlib.pyplot as plt

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(10, 4))
    plt.plot(timestamps, equity_curve, label="Equity")
    plt.xticks(rotation=45, ha="right")
    plt.title("Backtest Equity Curve")
    plt.tight_layout()
    plt.legend()
    plt.savefig(output)
    plt.close()
    return output
