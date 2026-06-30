from __future__ import annotations

from datetime import datetime, timezone

from app.runtime import RuntimeSnapshot
from app.types import RuntimeMode
from app.web_dashboard import UI_VERSION, WebDashboard
from data.models import AccountSnapshot, Balance, ConnectionEvent, EquityPoint, FillRecord, OrderTimelineEvent, Position, PricePoint, Side


def test_web_dashboard_serves_status_json() -> None:
    dashboard = WebDashboard(host="127.0.0.1", port=0, start_server=False)
    try:
        snapshot = RuntimeSnapshot(
            mode=RuntimeMode.PAPER,
            connection_status="streaming",
            account=AccountSnapshot(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                balances={"USDT": Balance(asset="USDT", free=1000.0)},
                net_asset_value=1000.0,
                available_quote_balance=1000.0,
            ),
            active_strategy="ema_trend",
            tracked_symbols=["BTC/USDT"],
            tracked_timeframes=["1m"],
            recent_fills=[
                FillRecord(
                    fill_id="fill-1",
                    order_id="order-1",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    quantity=0.1,
                    price=100.0,
                    fee=0.01,
                    fee_asset="USDT",
                    realized_pnl=0.0,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            ],
            order_timeline=[
                OrderTimelineEvent(
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    order_id="order-1",
                    client_order_id="client-1",
                    symbol="BTCUSDT",
                    side="BUY",
                    status="FILLED",
                    message="filled",
                    strategy_name="ema_trend",
                )
            ],
            connection_events=[
                ConnectionEvent(
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    channel="user_stream",
                    state="connected",
                    message="connected",
                )
            ],
            price_history={
                "BTCUSDT|1m": [
                    PricePoint(
                        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        symbol="BTC/USDT",
                        timeframe="1m",
                        open=99.0,
                        high=101.0,
                        low=98.5,
                        close=100.0,
                        volume=10.0,
                    )
                ]
            },
            equity_history=[
                EquityPoint(
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    net_asset_value=1000.0,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    session_pnl=0.0,
                )
            ],
            risk_state={"status": "active", "reason": "", "daily_realized_pnl": 0.0, "loss_streak": 0},
        )
        dashboard.render(snapshot)
        payload = dashboard.current_payload()
        assert payload["ui_version"] == UI_VERSION
        assert payload["mode"] == "paper"
        assert payload["connection_status"] == "streaming"
        assert payload["account"]["available_quote_balance"] == 1000.0
        assert payload["active_strategy"] == "ema_trend"
        assert payload["recent_fills"][0]["order_id"] == "order-1"
        assert "BTCUSDT|1m" in payload["price_history"]
    finally:
        dashboard.stop()


def test_web_dashboard_trims_heavy_payloads() -> None:
    dashboard = WebDashboard(host="127.0.0.1", port=0, start_server=False)
    try:
        balances = {
            f"ASSET{i}": Balance(asset=f"ASSET{i}", free=float(i), locked=0.0)
            for i in range(1, 80)
        }
        balances["USDT"] = Balance(asset="USDT", free=2500.0)
        positions = {
            f"COIN{i}USDT": Position(
                symbol=f"COIN{i}USDT",
                quantity=float(i),
                average_price=1.0 + i,
                market_price=1.2 + i,
                unrealized_pnl=float(i) * 0.5,
            )
            for i in range(1, 120)
        }
        snapshot = RuntimeSnapshot(
            mode=RuntimeMode.TESTNET,
            connection_status="streaming+synced",
            account=AccountSnapshot(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                balances=balances,
                net_asset_value=12500.0,
                available_quote_balance=2500.0,
            ),
            positions=positions,
            market_board={
                "updated_at": "2026-01-01T00:00:00+00:00",
                "source": "test",
                "rows": [{"symbol": f"ROW{i}USDT"} for i in range(300)],
                "sections": {
                    "gainers": [{"symbol": f"G{i}USDT"} for i in range(300)],
                    "losers": [{"symbol": f"L{i}USDT"} for i in range(300)],
                },
                "stats": {"tracked_pairs": 300},
            },
            equity_history=[
                EquityPoint(
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    net_asset_value=float(i),
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    session_pnl=float(i),
                )
                for i in range(150)
            ],
        )
        dashboard.render(snapshot)
        payload = dashboard.current_payload()
        assert "balances" not in payload["account"]
        assert payload["account"]["balance_count"] == 80
        assert len(payload["account"]["balance_preview"]) <= 12
        assert payload["position_stats"]["open_count"] == 119
        assert payload["position_stats"]["displayed_count"] == 60
        assert payload["position_stats"]["hidden_count"] == 59
        assert len(payload["positions"]) == 60
        assert len(payload["market_board"]["rows"]) == 180
        assert len(payload["market_board"]["sections"]["gainers"]) == 180
        assert len(payload["equity_history"]) == 120
        assert payload["payload_meta"]["trimmed"] is True
        assert payload["payload_meta"]["payload_bytes"] > 0
    finally:
        dashboard.stop()


def test_web_dashboard_exposes_lite_snapshot() -> None:
    dashboard = WebDashboard(host="127.0.0.1", port=0, start_server=False)
    try:
        snapshot = RuntimeSnapshot(
            mode=RuntimeMode.PAPER,
            connection_status="streaming",
            account=AccountSnapshot(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                balances={"USDT": Balance(asset="USDT", free=1234.0)},
                net_asset_value=1234.0,
                available_quote_balance=900.0,
            ),
            active_strategy="ema_trend",
            tracked_symbols=["BTC/USDT", "ETH/USDT"],
            tracked_timeframes=["1m", "5m"],
            market_board={
                "updated_at": "2026-01-01T00:00:00+00:00",
                "source": "test",
                "rows": [{"symbol": f"ROW{i}USDT"} for i in range(25)],
                "sections": {
                    "gainers": [{"symbol": f"G{i}USDT"} for i in range(25)],
                    "losers": [{"symbol": f"L{i}USDT"} for i in range(25)],
                },
                "stats": {"tracked_pairs": 25, "positive_pairs": 12, "negative_pairs": 13},
            },
        )
        dashboard.render(snapshot)
        lite_payload = dashboard.current_lite_payload()
        assert lite_payload["ui_version"] == UI_VERSION
        assert lite_payload["snapshot_revision"] == 1
        assert lite_payload["market_board"]["row_count"] == 25
        assert len(lite_payload["market_board"]["sections"]["gainers"]) == 8
        assert lite_payload["client_hints"]["lite_poll_ms"] == 1000
        assert lite_payload["account"]["available_quote_balance"] == 900.0
    finally:
        dashboard.stop()
