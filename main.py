import sys

from app.cli import main as legacy_main
from app.freqtrade_cli import main as freqtrade_main
from app.freqtrade_cli import should_handle_freqtrade_route


if __name__ == "__main__":
    if should_handle_freqtrade_route(sys.argv[1:]):
        freqtrade_main(sys.argv[1:])
    else:
        legacy_main()
