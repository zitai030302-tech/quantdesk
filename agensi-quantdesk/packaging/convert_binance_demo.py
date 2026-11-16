"""Normalize the published Jan 2024 Binance spot BTCUSDT 1h demo archive."""
import csv
import hashlib
import io
from pathlib import Path
import sys
import zipfile

EXPECTED = "cf873a185bd5b24b8e00034e49583fcb49928e0c3a45c6fc27a632a683655417"


def main():
    path = Path(sys.argv[1])
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError("archive does not match the documented Binance SHA-256")
    with (
        zipfile.ZipFile(path) as package,
        package.open("BTCUSDT-1h-2024-01.csv") as source,
        Path(sys.argv[2]).open("x", encoding="utf-8", newline="") as output,
    ):
        reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8"))
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("timestamp", "close_time", "open", "high", "low", "close", "volume",
                         "quote_volume", "trades"))
        for row in reader:
            writer.writerow((row[0], row[6], *row[1:6], row[7], row[8]))


if __name__ == "__main__":
    main()
