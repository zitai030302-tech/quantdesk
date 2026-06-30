from __future__ import annotations

from datetime import timezone

from app.runtime import RuntimeSnapshot

try:  # pragma: no cover - rendering specifics are not essential for unit tests.
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    Console = None
    Table = None


class TerminalDashboard:
    def __init__(self) -> None:
        self.console = Console() if Console else None

    def render(self, snapshot: RuntimeSnapshot) -> None:
        if not self.console or not Table:
            self._fallback_render(snapshot)
            return

        self.console.clear()
        summary = Table(title="系统状态")
        summary.add_column("字段")
        summary.add_column("值")
        summary.add_row("模式", self._translate_mode(snapshot.mode.value))
        summary.add_row("连接", self._translate_status(snapshot.connection_status))
        if snapshot.account:
            summary.add_row("净值", f"{snapshot.account.net_asset_value:,.2f}")
            summary.add_row("可用 USDT", f"{snapshot.account.available_quote_balance:,.2f}")
        summary.add_row("风险状态", self._translate_status(snapshot.risk_state.get("status", "unknown")))
        summary.add_row("风险原因", snapshot.risk_state.get("reason", "") or "无")
        self.console.print(summary)

        positions = Table(title="当前持仓")
        positions.add_column("交易对")
        positions.add_column("数量")
        positions.add_column("均价")
        positions.add_column("现价")
        positions.add_column("浮盈亏")
        for position in snapshot.positions.values():
            if not position.is_open:
                continue
            positions.add_row(
                position.symbol,
                f"{position.quantity:.6f}",
                f"{position.average_price:.2f}",
                f"{position.market_price:.2f}",
                f"{position.unrealized_pnl:.2f}",
            )
        self.console.print(positions)

        signals = Table(title="最近信号")
        signals.add_column("时间")
        signals.add_column("交易对")
        signals.add_column("信号")
        signals.add_column("原因")
        for signal in snapshot.recent_signals[-6:]:
            signals.add_row(
                signal.timestamp.astimezone(timezone.utc).strftime("%H:%M:%S"),
                signal.symbol,
                self._translate_signal(signal.signal_type.value),
                signal.reason,
            )
        self.console.print(signals)

        orders = Table(title="最近订单")
        orders.add_column("交易对")
        orders.add_column("方向")
        orders.add_column("状态")
        orders.add_column("数量")
        orders.add_column("成交均价")
        for order in snapshot.recent_orders[-6:]:
            orders.add_row(
                order.symbol,
                self._translate_side(order.side.value),
                self._translate_status(order.status.value),
                f"{order.quantity:.6f}",
                f"{order.average_price or 0.0:.2f}",
            )
        self.console.print(orders)

    @staticmethod
    def _fallback_render(snapshot: RuntimeSnapshot) -> None:
        print(
            f"[控制台] 模式={TerminalDashboard._translate_mode(snapshot.mode.value)} "
            f"连接={TerminalDashboard._translate_status(snapshot.connection_status)} "
            f"净值={(snapshot.account.net_asset_value if snapshot.account else 0.0):.2f}"
        )

    @staticmethod
    def _translate_mode(value: str) -> str:
        return {
            "paper": "仿真盘",
            "testnet": "测试盘",
            "monitor": "主网观察",
            "backtest": "回测",
            "live": "实盘(禁用)",
        }.get(str(value).lower(), value)

    @staticmethod
    def _translate_status(value: str) -> str:
        return {
            "starting": "启动中",
            "initialized": "已初始化",
            "ready": "就绪",
            "streaming": "实时流中",
            "streaming+user-stream": "行情与账户流",
            "streaming+synced": "已同步",
            "bootstrap": "引导同步中",
            "connecting": "连接中",
            "connected": "已连接",
            "reconnecting": "重连中",
            "subscribed": "已订阅",
            "active": "正常",
            "paused": "已暂停",
            "protect": "保护模式",
            "new": "新建",
            "partially_filled": "部分成交",
            "filled": "已成交",
            "canceled": "已撤单",
            "rejected": "已拒绝",
            "expired": "已过期",
            "unknown": "未知",
        }.get(str(value).lower(), value)

    @staticmethod
    def _translate_signal(value: str) -> str:
        return {
            "BUY": "买入",
            "SELL": "卖出",
            "FLAT": "平仓",
            "HOLD": "观望",
        }.get(value, value)

    @staticmethod
    def _translate_side(value: str) -> str:
        return {
            "BUY": "买入",
            "SELL": "卖出",
        }.get(value, value)
