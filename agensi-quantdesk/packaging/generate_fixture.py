"""Print deterministic, synthetic BTC-labeled OHLCV for offline smoke tests."""
import csv
from datetime import datetime, timedelta, timezone
import sys


def main():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pattern = [100, 99, 98, 97, 96, 95, 94, 97, 100, 102, 105, 106, 103, 98, 92, 91]
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
    last = 100
    for i in range(160):
        close = pattern[i % len(pattern)] + i // len(pattern)
        writer.writerow([(start + timedelta(hours=i)).isoformat(), last, max(last, close) + 1,
                         min(last, close) - 1, close, 10 + i % 7])
        last = close


if __name__ == "__main__":
    main()
