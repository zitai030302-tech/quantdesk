"""Run the separately installed QuantDesk Agensi runtime in the local interpreter."""
import json
import sys
from importlib.metadata import PackageNotFoundError, version

REQUIRED = "0.1.0"


def main():
    installed = None
    if sys.version_info >= (3, 11):
        try:
            installed = version("quantdesk-agensi-runtime")
        except PackageNotFoundError:
            pass
    if installed != REQUIRED:
        print(json.dumps({"status": "error", "message": "Requires Python 3.11+ and the reviewed QuantDesk Agensi runtime wheel",
                          "required_version": REQUIRED, "installed_version": installed}), file=sys.stderr)
        return 2
    from quantdesk_agensi_runtime.cli import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
