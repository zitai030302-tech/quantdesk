import asyncio
import json
from pathlib import Path

from app.config_loader import load_config
from app.engine import TradingEngine
from app.types import RuntimeMode
from data.market_data import CSVReplayMarketDataFeed
from data.models import AccountSnapshot, Balance, Bar, Signal, SignalType, utc_now
from data.repositories import TradingRepository
from data.sqlite import SQLiteStorage
from execution.filters import extract_symbol_rules
from execution.paper_broker import PaperBroker
from risk.manager import RiskManager
from strategies.base import BaseStrategy


class AlwaysBuyStrategy(BaseStrategy):
    def generate_signal(self, bar: Bar, position):  # type: ignore[override]
        return Signal(
            strategy_name="always_buy",
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            signal_type=SignalType.BUY,
            timestamp=utc_now(),
            reason="测试用持续买入信号",
        )


def _build_engine(tmp_path: Path) -> tuple[TradingEngine, PaperBroker]:
    base_dir = Path(__file__).resolve().parents[2]
    config = load_config(base_dir / "config" / "config.yaml")
    config.app.mode = RuntimeMode.PAPER
    config.app.dashboard.enabled = False
    config.exchange.symbols = ["BTC/USDT"]
    config.exchange.timeframes = ["1m"]
    config.exchange.warmup_limit = 8
    config.risk.atr_period = 3
    config.storage.sqlite_path = str(tmp_path / "engine-sync.db")
    config.execution.paper_initial_cash = 1000.0

    storage = SQLiteStorage(tmp_path / "engine-sync.db")
    storage.initialize()
    repository = TradingRepository(storage)
    exchange_info = json.loads((base_dir / "tests" / "fixtures" / "exchange_info.json").read_text(encoding="utf-8"))
    rules = extract_symbol_rules(exchange_info)
    adapter = PaperBroker(
        rules=rules,
        initial_cash=1000.0,
        fee_rate=config.execution.fee_rate,
        slippage_bps=config.risk.slippage_bps,
    )
    engine = TradingEngine(
        config=config,
        repository=repository,
        market_data_feed=CSVReplayMarketDataFeed(str(base_dir / "tests" / "fixtures" / "btcusdt_1m_sample.csv")),
        adapter=adapter,
        risk_manager=RiskManager(config.risk, RuntimeMode.PAPER),
        dashboard=None,
    )
    return engine, adapter


def test_manual_order_uses_fresh_account_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine, adapter = _build_engine(tmp_path)
        await engine.initialize()
        adapter.balances["USDT"].free = 5.0
        engine.cache.account_snapshot = AccountSnapshot(
            timestamp=utc_now(),
            balances={"USDT": Balance(asset="USDT", free=1000.0)},
            net_asset_value=1000.0,
            available_quote_balance=1000.0,
        )

        await engine._handle_manual_order_command(
            {"symbol": "BTCUSDT", "timeframe": "1m", "side": "BUY", "order_type": "MARKET"}
        )

        events = engine.control_plane.describe()["events"]
        assert events
        assert events[0]["action"] == "manual_order"
        assert events[0]["success"] is False
        assert not adapter.orders
        assert adapter.balances["USDT"].free == 5.0

    asyncio.run(scenario())


def test_handle_bar_refreshes_account_after_fill(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine, adapter = _build_engine(tmp_path)
        await engine.initialize()
        strategy = AlwaysBuyStrategy("always_buy", "BTC/USDT", "1m", {})
        for existing_bar in engine.bar_histories[("BTCUSDT", "1m")]:
            strategy.on_bar(existing_bar)
        bar = engine.bar_histories[("BTCUSDT", "1m")][-1]

        await engine._handle_bar(bar, strategy, engine.rule_map["BTCUSDT"])

        assert adapter.orders
        assert engine.cache.account_snapshot is not None
        assert engine.cache.account_snapshot.available_quote_balance == adapter.balances["USDT"].free
        assert engine.cache.account_snapshot.available_quote_balance < 1000.0

    asyncio.run(scenario())


def test_trade_plan_metrics_are_present(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine, _adapter = _build_engine(tmp_path)
        await engine.initialize()
        plans = engine._build_trade_plans()

        assert plans
        first_plan = plans[0]
        assert "notional_value" in first_plan
        assert "risk_amount" in first_plan
        assert "reward_amount" in first_plan
        assert "risk_reward_ratio" in first_plan

        analysis = await engine.analyze_symbol("BTCUSDT", "1m", "ema_trend")
        assert analysis["ok"] is True
        assert "notional_value" in analysis
        assert "risk_amount" in analysis
        assert "reward_amount" in analysis
        assert "risk_reward_ratio" in analysis

    asyncio.run(scenario())
