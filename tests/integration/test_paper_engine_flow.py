from pathlib import Path

import json

from app.engine import TradingEngine
from app.types import RuntimeMode
from data.market_data import CSVReplayMarketDataFeed
from data.repositories import TradingRepository
from data.sqlite import SQLiteStorage
from execution.filters import extract_symbol_rules
from execution.paper_broker import PaperBroker
from risk.manager import RiskManager
from app.config_loader import load_config


def test_paper_engine_flow(tmp_path: Path) -> None:
    base_dir = Path(__file__).resolve().parents[2]
    config = load_config(base_dir / "config" / "config.yaml")
    config.app.mode = RuntimeMode.PAPER
    config.app.dashboard.enabled = False
    config.exchange.symbols = ["BTC/USDT"]
    config.exchange.timeframes = ["1m"]
    config.exchange.warmup_limit = 10
    config.strategy.active_strategy = "ema_trend"
    config.strategy.ema_trend.values = {"fast_period": 3, "slow_period": 5, "atr_period": 3}
    config.storage.sqlite_path = str(tmp_path / "integration.db")
    config.execution.paper_initial_cash = 10000.0

    storage = SQLiteStorage(tmp_path / "integration.db")
    storage.initialize()
    repository = TradingRepository(storage)
    exchange_info = json.loads((base_dir / "tests" / "fixtures" / "exchange_info.json").read_text(encoding="utf-8"))
    rules = extract_symbol_rules(exchange_info)
    adapter = PaperBroker(rules, initial_cash=10000.0, fee_rate=config.execution.fee_rate, slippage_bps=config.risk.slippage_bps)
    engine = TradingEngine(
        config=config,
        repository=repository,
        market_data_feed=CSVReplayMarketDataFeed(str(base_dir / "tests" / "fixtures" / "btcusdt_1m_sample.csv")),
        adapter=adapter,
        risk_manager=RiskManager(config.risk, RuntimeMode.PAPER),
        dashboard=None,
    )

    __import__("asyncio").run(engine.run(max_bars=20))
    signals = repository.recent_signals(limit=20)
    candles = repository.list_candles("BTC/USDT", "1m")
    assert len(candles) >= 20
    assert signals
