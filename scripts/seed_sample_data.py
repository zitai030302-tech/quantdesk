from pathlib import Path

from data.csv_loader import load_ohlcv_csv
from data.repositories import TradingRepository
from data.sqlite import SQLiteStorage


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    storage = SQLiteStorage(base_dir / "data" / "trading.db")
    storage.initialize()
    repository = TradingRepository(storage)
    for bar in load_ohlcv_csv(base_dir / "tests" / "fixtures" / "btcusdt_1m_sample.csv", "BTC/USDT", "1m"):
        repository.save_candle(bar)
    print("Seeded sample candle data.")


if __name__ == "__main__":
    main()
