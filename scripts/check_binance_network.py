from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.network_diagnostics import BinanceNetworkDiagnosticsService


async def main() -> None:
    service = BinanceNetworkDiagnosticsService()
    snapshot = await service.refresh(force=True)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
