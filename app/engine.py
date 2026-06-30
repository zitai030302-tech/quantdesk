from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.alerts import ConsoleAlerter
from app.control import ControlPlane
from app.dashboard import TerminalDashboard
from app.runtime import RuntimeSnapshot
from app.supervisor import Supervisor
from app.types import RiskStatus, RuntimeMode, SystemConfig, normalize_symbol
from data.cache import RuntimeCache
from data.market_data import MarketDataFeed
from data.market_overview import BinanceMarketOverviewService
from data.network_diagnostics import BinanceNetworkDiagnosticsService
from data.models import AccountSnapshot, Balance, Bar, ExchangeRule, FillRecord, PnLSnapshot, Position, RiskEvent, Signal, SignalType, utc_now
from data.repositories import TradingRepository
from execution.adapter_base import ExchangeAdapter
from execution.order_manager import OrderManager
from execution.paper_broker import PaperBroker
from execution.validators import round_to_step, round_to_tick
from risk.manager import RiskManager
from strategies.base import BaseStrategy
from strategies.registry import build_strategy_from_config, resolve_strategy_name, strategy_public_name


LOGGER = logging.getLogger("app.engine")


class TradingEngine:
    def __init__(
        self,
        config: SystemConfig,
        repository: TradingRepository,
        market_data_feed: MarketDataFeed,
        adapter: ExchangeAdapter,
        risk_manager: RiskManager,
        dashboard: TerminalDashboard | None = None,
        alerter: ConsoleAlerter | None = None,
        control_plane: ControlPlane | None = None,
        market_overview_service: BinanceMarketOverviewService | None = None,
        network_diagnostics_service: BinanceNetworkDiagnosticsService | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.market_data_feed = market_data_feed
        self.adapter = adapter
        self.risk_manager = risk_manager
        self.dashboard = dashboard
        self.alerter = alerter or ConsoleAlerter()
        self.control_plane = control_plane or ControlPlane()
        self.supervisor = Supervisor()
        self.cache = RuntimeCache()
        self.order_manager = OrderManager(adapter, risk_manager, config.execution)
        self.strategies: dict[tuple[str, str], BaseStrategy] = {}
        self.rule_map: dict[str, ExchangeRule] = {}
        self.bar_histories: dict[tuple[str, str], list[Bar]] = defaultdict(list)
        self.market_overview_service = market_overview_service
        self.market_board: dict[str, Any] = {"updated_at": None, "source": "disabled", "rows": []}
        self.network_diagnostics_service = network_diagnostics_service
        self.network_diagnostics: dict[str, Any] = {"updated_at": None, "summary": "等待网络诊断", "recommendations": []}
        self.connection_status = "starting"
        self.loop: asyncio.AbstractEventLoop | None = None

    async def initialize(self) -> None:
        self.rule_map = await self.adapter.get_exchange_rules()
        self.cache.record_connection_event("engine", "initialized", "交易引擎初始化完成")
        for symbol in self.config.exchange.symbols:
            for timeframe in self.config.exchange.timeframes:
                strategy = self._build_strategy(symbol, timeframe)
                warmup_bars = await self.market_data_feed.warmup(symbol, timeframe, self.config.exchange.warmup_limit)
                for bar in warmup_bars:
                    self.repository.save_candle(bar)
                    strategy.on_bar(bar)
                    self.bar_histories[(normalize_symbol(symbol), timeframe)].append(bar)
                    self.cache.store_bar(bar)
                self.strategies[(normalize_symbol(symbol), timeframe)] = strategy
        self.connection_status = "ready"
        self.cache.record_connection_event("market_data", "ready", "历史预热完成")
        await self._refresh_market_board(force=True)
        await self._refresh_network_diagnostics(force=True)

    async def run(self, max_bars: int | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        await self.initialize()
        coroutines = [
            self._run_symbol_timeframe(symbol, timeframe, max_bars=max_bars)
            for symbol in self.config.exchange.symbols
            for timeframe in self.config.exchange.timeframes
        ]
        coroutines.append(self._render_loop(max_cycles=max_bars))
        if self.config.app.mode in {RuntimeMode.TESTNET, RuntimeMode.MONITOR} or (
            self.config.app.mode == RuntimeMode.PAPER and max_bars is None
        ):
            coroutines.append(self._consume_user_events())
        try:
            await self.supervisor.run(*coroutines)
        finally:
            stop = getattr(self.dashboard, "stop", None)
            if callable(stop):
                stop()

    async def _run_symbol_timeframe(self, symbol: str, timeframe: str, max_bars: int | None = None) -> None:
        processed = 0
        strategy = self.strategies[(normalize_symbol(symbol), timeframe)]
        rule = self.rule_map[normalize_symbol(symbol)]
        async for bar in self.market_data_feed.stream_bars(symbol, timeframe):
            self.connection_status = "streaming"
            await self._handle_bar(bar, strategy, rule)
            processed += 1
            if max_bars is not None and processed >= max_bars:
                break

    async def _handle_bar(self, bar: Bar, strategy: BaseStrategy, rule: ExchangeRule) -> None:
        history_key = (normalize_symbol(bar.symbol), bar.timeframe)
        self.bar_histories[history_key].append(bar)
        self.cache.store_bar(bar)
        self.repository.save_candle(bar)
        strategy.on_bar(bar)
        refresh_account: AccountSnapshot | None

        if isinstance(self.adapter, PaperBroker):
            for fill in self.adapter.update_mark_price(bar):
                await self._handle_fill(fill)

        account = await self.adapter.get_account_snapshot()
        refresh_account = account
        positions = await self.adapter.get_positions()
        position = positions.get(normalize_symbol(bar.symbol))
        signal = strategy.generate_signal(bar, position)

        if self.config.app.mode == RuntimeMode.MONITOR:
            await self._handle_monitor_signal(signal, account, position, rule, self.bar_histories[history_key], bar)
            await self._refresh_account_state(account)
            return

        self.cache.recent_signals.append(signal)
        self.repository.save_signal(signal)

        if signal.signal_type != SignalType.HOLD:
            order, reasons = await self.order_manager.handle_signal(
                signal=signal,
                account=account,
                position=position,
                rule=rule,
                bar_history=self.bar_histories[history_key],
            )
            if order:
                self._remember_order(order, "信号已通过，订单已提交")
                refresh_account = None
                if order.status.value == "FILLED":
                    if isinstance(self.adapter, PaperBroker):
                        fill = self.adapter.consume_fill(order.order_id)
                        if fill is not None:
                            await self._handle_fill(fill)
                    refreshed_positions = await self.adapter.get_positions()
                    tracked = refreshed_positions.get(normalize_symbol(bar.symbol), Position(symbol=normalize_symbol(bar.symbol)))
                    self.repository.save_position(tracked)
            elif reasons:
                event = RiskEvent(
                    timestamp=utc_now(),
                    event_type="risk_block",
                    message="; ".join(reasons),
                    status=self.risk_manager.risk_status(),
                    details={"symbol": bar.symbol, "signal": signal.signal_type.value},
                )
                self.repository.save_risk_event(event)
                self.cache.risk_events.append(event)
                LOGGER.info("signal blocked | %s | %s", bar.symbol, ", ".join(reasons))

        await self._refresh_account_state(refresh_account)

    async def _handle_monitor_signal(
        self,
        signal: Signal,
        account: AccountSnapshot,
        position: Position | None,
        rule: ExchangeRule,
        bar_history: list[Bar],
        bar: Bar,
    ) -> None:
        if signal.signal_type == SignalType.HOLD:
            signal.metadata["monitor_plan"] = {
                "status": "watch",
                "action": "WAIT",
                "message": "当前未触发交易条件，继续观察。",
            }
        else:
            decision = self.risk_manager.evaluate_signal(signal, account, position, rule, bar_history)
            if decision.allowed:
                signal.metadata["monitor_plan"] = {
                    "status": "planned",
                    "action": signal.signal_type.value,
                    "reference_price": bar.close,
                    "quantity": decision.quantity,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "message": "主网观察模式仅生成计划，不会真实下单。",
                }
                signal.reason = (
                    f"{signal.reason} | 观察计划：{signal.signal_type.value} {decision.quantity:.6f} "
                    f"@ {bar.close:.2f}"
                )
                if decision.stop_loss is not None and decision.take_profit is not None:
                    signal.reason += f" 止损 {decision.stop_loss:.2f} 止盈 {decision.take_profit:.2f}"
            else:
                signal.metadata["monitor_plan"] = {
                    "status": "blocked",
                    "action": signal.signal_type.value,
                    "reference_price": bar.close,
                    "reasons": decision.reasons,
                    "message": "主网观察模式下，该交易计划已被风控拦截。",
                }
                signal.reason = f"{signal.reason} | 已拦截：{'；'.join(decision.reasons)}"

        self.cache.recent_signals.append(signal)
        self.repository.save_signal(signal)

    async def _handle_fill(self, fill: FillRecord) -> None:
        self.repository.save_fill(fill)
        self.cache.recent_fills.append(fill)
        if fill.realized_pnl != 0:
            event = self.risk_manager.on_trade_closed(fill)
            if event:
                self.repository.save_risk_event(event)
                self.cache.risk_events.append(event)
        positions = await self.adapter.get_positions()
        position = positions.get(fill.symbol, Position(symbol=fill.symbol))
        self.repository.save_position(position)

    async def _consume_user_events(self) -> None:
        async for event in self.adapter.stream_user_events():
            await self._handle_user_event(event)

    async def _handle_user_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event", "")
        if event_type == "connectionEvent":
            self.cache.record_connection_event(
                event.get("channel", "unknown"),
                event.get("state", "unknown"),
                event.get("message", ""),
                event.get("details", {}),
            )
            return
        if event_type == "subscriptionStarted":
            self.connection_status = "streaming+user-stream"
            self.cache.record_connection_event(
                "user_stream",
                "subscribed",
                f"账户流订阅已启动：{event.get('subscription_id', 'unknown')}",
            )
            return
        if event_type == "accountSnapshot" and event.get("account") is not None:
            self.connection_status = "streaming+synced"
            await self._refresh_account_state(event["account"])
            return
        if event_type == "orderUpdate" and event.get("order") is not None:
            self._remember_order(event["order"], "收到账户流订单更新")
            return
        if event_type == "fill" and event.get("fill") is not None:
            await self._handle_fill(event["fill"])
            return
        if event_type == "executionReport":
            if event.get("order") is not None:
                self._remember_order(event["order"], "收到账户流订单更新")
            if event.get("fill") is not None:
                await self._handle_fill(event["fill"])
            return
        if event_type in {"streamError", "streamTerminated", "syncWarning"}:
            details = event.get("details", {})
            risk_event = self.risk_manager.enter_protect_mode(event.get("message", event_type), details)
            self.repository.save_risk_event(risk_event)
            self.cache.risk_events.append(risk_event)
            self.connection_status = "protect"
            self.cache.record_connection_event("user_stream", "protect", risk_event.message, details)
            self.alerter.notify_risk_event(risk_event)
            return
        if event_type == "externalLockUpdate":
            risk_event = RiskEvent(
                timestamp=utc_now(),
                event_type="external_lock_update",
                message="检测到外部余额锁定更新",
                status=self.risk_manager.risk_status(),
                details=event.get("payload", {}),
            )
            self.repository.save_risk_event(risk_event)
            self.cache.risk_events.append(risk_event)

    async def _refresh_account_state(self, account: AccountSnapshot | None = None) -> None:
        snapshot = account or await self.adapter.get_account_snapshot()
        positions = await self.adapter.get_positions()
        self._mark_positions_to_market(positions)
        snapshot = self._revalue_account_snapshot(snapshot, positions)
        self.cache.account_snapshot = snapshot
        self.cache.balances = {asset: balance.total for asset, balance in snapshot.balances.items()}
        self.cache.positions = positions
        for position in positions.values():
            self.repository.save_position(position)
        pnl_snapshot = PnLSnapshot(
            date=snapshot.timestamp.date().isoformat(),
            realized_pnl=self.risk_manager.state.realized_pnl,
            unrealized_pnl=sum(position.unrealized_pnl for position in positions.values()),
            net_asset_value=snapshot.net_asset_value,
        )
        self.cache.record_equity(
            snapshot,
            realized_pnl=pnl_snapshot.realized_pnl,
            unrealized_pnl=pnl_snapshot.unrealized_pnl,
        )
        self.repository.save_daily_pnl(pnl_snapshot)

    async def _render_loop(self, max_cycles: int | None = None) -> None:
        if not self.dashboard:
            return
        cycles = 0
        while True:
            await self._refresh_market_board()
            await self._refresh_network_diagnostics()
            await self._process_control_commands()
            snapshot = RuntimeSnapshot(
                mode=self.config.app.mode,
                connection_status=self.connection_status,
                active_strategy=self.config.strategy.active_strategy,
                tracked_symbols=list(self.config.exchange.symbols),
                tracked_timeframes=list(self.config.exchange.timeframes),
                market_board=self.market_board,
                network_diagnostics=self.network_diagnostics,
                trade_plans=self._build_trade_plans(),
                control_state=self.control_plane.describe(),
                account=self.cache.account_snapshot,
                positions=self.cache.positions,
                recent_signals=list(self.cache.recent_signals),
                recent_orders=list(self.cache.recent_orders),
                recent_fills=list(self.cache.recent_fills),
                order_timeline=list(self.cache.order_timeline),
                connection_events=list(self.cache.connection_events),
                price_history={key: list(series) for key, series in self.cache.price_history.items()},
                equity_history=list(self.cache.equity_history),
                risk_events=list(self.cache.risk_events),
                risk_state=self.risk_manager.snapshot(
                    self.cache.account_snapshot
                    or AccountSnapshot(
                        timestamp=utc_now(),
                        balances={"USDT": Balance(asset="USDT", free=0.0)},
                        net_asset_value=0.0,
                        available_quote_balance=0.0,
                    ),
                    self.cache.positions,
                ),
            )
            self.dashboard.render(snapshot)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            await asyncio.sleep(self.config.app.dashboard.refresh_interval_sec)

    async def _process_control_commands(self) -> None:
        for command in self.control_plane.drain():
            action = command.action
            params = command.params
            if action == "pause":
                reason = str(params.get("reason") or "来自网页控制台的手动暂停")
                event = self.risk_manager.pause_trading(reason, {"source": "web_control"})
                self.repository.save_risk_event(event)
                self.cache.risk_events.append(event)
                self.control_plane.record(action, True, "交易已暂停，新信号不会继续开仓。")
                continue

            if action == "resume":
                if self.risk_manager.risk_status() == RiskStatus.PROTECT:
                    self.control_plane.record(action, False, "当前处于保护模式，必须先排查异常，不能直接恢复。")
                    continue
                self.risk_manager.clear_pause()
                self.control_plane.record(action, True, "交易已恢复，系统会继续处理新信号。")
                continue

            if action == "switch_strategy":
                raw_name = str(params.get("strategy") or "").strip()
                if not raw_name:
                    self.control_plane.record(action, False, "没有收到可切换的策略名称。")
                    continue
                try:
                    internal_name = resolve_strategy_name(raw_name)
                except ValueError as exc:
                    self.control_plane.record(action, False, str(exc))
                    continue
                if internal_name == self.config.strategy.active_strategy:
                    self.control_plane.record(action, True, f"当前已经是 {strategy_public_name(internal_name)}。")
                    continue
                self.config.strategy.active_strategy = internal_name
                self._rebuild_strategies()
                self.control_plane.record(action, True, f"已切换到 {strategy_public_name(internal_name)}。")
                continue

            if action == "manual_order":
                await self._handle_manual_order_command(params)
                continue

            if action == "cancel_order":
                await self._handle_cancel_order_command(params)
                continue

            self.control_plane.record(action, False, f"暂不支持的控制动作：{action}")

    def _rebuild_strategies(self) -> None:
        rebuilt: dict[tuple[str, str], BaseStrategy] = {}
        for symbol in self.config.exchange.symbols:
            for timeframe in self.config.exchange.timeframes:
                strategy = self._build_strategy(symbol, timeframe)
                for bar in self.bar_histories[(normalize_symbol(symbol), timeframe)]:
                    strategy.on_bar(bar)
                rebuilt[(normalize_symbol(symbol), timeframe)] = strategy
        self.strategies = rebuilt

    def _build_trade_plans(self) -> list[dict[str, Any]]:
        account = self.cache.account_snapshot or AccountSnapshot(
            timestamp=utc_now(),
            balances={self.config.exchange.quote_asset: Balance(asset=self.config.exchange.quote_asset, free=0.0)},
            net_asset_value=0.0,
            available_quote_balance=0.0,
        )
        plans: list[dict[str, Any]] = []
        for symbol in self.config.exchange.symbols:
            for timeframe in self.config.exchange.timeframes:
                key = (normalize_symbol(symbol), timeframe)
                strategy = self.strategies.get(key)
                rule = self.rule_map.get(normalize_symbol(symbol))
                latest_bar = self.cache.latest_bars.get(key)
                bar_history = self.bar_histories.get(key, [])
                position = self.cache.positions.get(normalize_symbol(symbol))
                if not strategy or not rule or not latest_bar or not bar_history:
                    continue

                signal = strategy.generate_signal(latest_bar, position)
                entry_price = latest_bar.close
                plan = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_name": self.config.strategy.active_strategy,
                    "strategy_label": strategy_public_name(self.config.strategy.active_strategy),
                    "signal_type": signal.signal_type.value,
                    "reason": signal.reason,
                    "entry_price": entry_price,
                    "position_open": bool(position and position.is_open),
                    "position_quantity": position.quantity if position else 0.0,
                    "status": "watch",
                    "status_label": "继续观察",
                    "quantity": 0.0,
                    "stop_loss": None,
                    "take_profit": None,
                    "risk_budget": account.net_asset_value * self.config.risk.max_trade_risk_pct,
                    "blocked_reasons": [],
                    "notional_value": 0.0,
                    "risk_amount": 0.0,
                    "reward_amount": 0.0,
                    "risk_reward_ratio": None,
                }

                if position and position.is_open:
                    plan["status"] = "position"
                    plan["status_label"] = "已有持仓"
                    plan["entry_price"] = position.average_price or entry_price
                    plan["position_quantity"] = position.quantity

                if signal.signal_type != SignalType.HOLD:
                    decision = self.risk_manager.evaluate_signal(signal, account, position, rule, bar_history)
                    plan["quantity"] = decision.quantity
                    plan["stop_loss"] = decision.stop_loss
                    plan["take_profit"] = decision.take_profit
                    plan["blocked_reasons"] = decision.reasons
                    plan.update(self._derive_trade_metrics(entry_price, decision.quantity, decision.stop_loss, decision.take_profit))
                    if decision.allowed:
                        plan["status"] = "planned"
                        plan["status_label"] = "可执行计划"
                    else:
                        plan["status"] = "blocked"
                        plan["status_label"] = "风控拦截"

                plans.append(plan)

        status_order = {"planned": 0, "position": 1, "blocked": 2, "watch": 3}
        plans.sort(key=lambda item: (status_order.get(str(item["status"]), 9), item["symbol"], item["timeframe"]))
        return plans

    async def _refresh_market_board(self, force: bool = False) -> None:
        if self.market_overview_service is None:
            return
        try:
            await self.market_overview_service.top_gainers(force=force)
            self.market_board = self.market_overview_service.snapshot()
        except Exception as exc:
            self.market_board = {
                "updated_at": self.market_board.get("updated_at"),
                "source": "error",
                "rows": self.market_board.get("rows", []),
                "message": f"涨幅榜暂时不可用：{exc}",
            }

    async def _refresh_network_diagnostics(self, force: bool = False) -> None:
        if self.network_diagnostics_service is None:
            return
        try:
            await self.network_diagnostics_service.refresh(force=force)
            self.network_diagnostics = self.network_diagnostics_service.snapshot()
        except Exception as exc:
            self.network_diagnostics = {
                "updated_at": self.network_diagnostics.get("updated_at"),
                "summary": f"网络诊断暂时不可用：{exc}",
                "recommendations": [
                    "如果你在用 Shadowrocket / Clash，请先确认 Binance 域名没有被错误地走美国节点。"
                ],
            }

    def _remember_order(self, order: Any, message: str) -> None:
        self.repository.save_order(order)
        recent = list(self.cache.recent_orders)[-8:]
        duplicate = any(
            item.order_id == order.order_id and item.status == order.status and item.updated_at == order.updated_at
            for item in recent
        )
        if not duplicate:
            self.cache.recent_orders.append(order)
        self.cache.record_order_event(order, message)
        for strategy in self.strategies.values():
            if normalize_symbol(strategy.symbol) == order.symbol:
                strategy.on_order_update(order)

    async def _handle_manual_order_command(self, params: dict[str, Any]) -> None:
        if self.config.app.mode not in {RuntimeMode.PAPER, RuntimeMode.TESTNET}:
            self.control_plane.record("manual_order", False, "网页手动下单只在仿真盘和测试盘开放。")
            return

        symbol = str(params.get("symbol") or "").strip().upper()
        timeframe = str(params.get("timeframe") or self.config.exchange.timeframes[0]).strip() or self.config.exchange.timeframes[0]
        side = str(params.get("side") or "BUY").strip().upper()
        order_type = str(params.get("order_type") or self.config.execution.default_order_type).strip().upper()
        if not symbol:
            self.control_plane.record("manual_order", False, "手动下单缺少交易对。")
            return
        if side not in {"BUY", "SELL"}:
            self.control_plane.record("manual_order", False, "手动下单方向只支持 BUY 或 SELL。")
            return
        if order_type not in {"MARKET", "LIMIT"}:
            self.control_plane.record("manual_order", False, "手动下单类型只支持 MARKET 或 LIMIT。")
            return

        analysis = await self.analyze_symbol(symbol=symbol, timeframe=timeframe, strategy_name=params.get("strategy"))
        if not analysis.get("ok", False):
            self.control_plane.record("manual_order", False, str(analysis.get("message") or "无法生成手动下单分析。"))
            return

        normalized_symbol = normalize_symbol(symbol)
        latest_bar = await self._latest_or_warmup_bar(symbol, timeframe)
        if latest_bar is None:
            self.control_plane.record("manual_order", False, "手动下单前没有可用的最新价格。")
            return

        rule = self.rule_map.get(normalized_symbol)
        if rule is None:
            all_rules = await self.adapter.get_exchange_rules()
            rule = all_rules.get(normalized_symbol)
            if rule is not None:
                self.rule_map[normalized_symbol] = rule
        if rule is None:
            self.control_plane.record("manual_order", False, f"当前没有 {symbol} 的交易规则，暂时无法下单。")
            return

        account = await self._current_account_snapshot()
        positions = await self.adapter.get_positions()
        position = positions.get(normalized_symbol)
        raw_quantity = self._parse_optional_float(params.get("quantity"))
        raw_price = self._parse_optional_float(params.get("price"))

        from data.models import OrderRequest, OrderType, Side

        if side == "BUY":
            synthetic_signal = Signal(
                strategy_name=str(params.get("strategy") or self.config.strategy.active_strategy),
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                timestamp=utc_now(),
                reason=f"网页手动下单 | {analysis.get('summary') or analysis.get('reason') or '基于当前分析计划提交'}",
            )
            decision = self.risk_manager.evaluate_signal(
                synthetic_signal,
                account,
                position,
                rule,
                self.bar_histories.get((normalized_symbol, timeframe), [latest_bar]),
            )
            if not decision.allowed:
                self.control_plane.record("manual_order", False, "；".join(decision.reasons))
                return
            quantity = raw_quantity if raw_quantity and raw_quantity > 0 else decision.quantity
            if quantity > decision.quantity + 1e-12:
                self.control_plane.record(
                    "manual_order",
                    False,
                    f"手动买入数量超过风控上限，当前最多允许 {decision.quantity:.6f}。",
                )
                return
            quantity = round_to_step(quantity, rule.step_size)
            price = round_to_tick(raw_price, rule.tick_size) if order_type == "LIMIT" and raw_price else None
            if order_type == "LIMIT" and price is None:
                self.control_plane.record("manual_order", False, "限价单必须填写价格。")
                return
            digest = hashlib.sha256(f"manual-buy-{normalized_symbol}-{utc_now().isoformat()}-{uuid4()}".encode("utf-8")).hexdigest()[:16]
            request = OrderRequest(
                symbol=normalized_symbol,
                side=Side.BUY,
                order_type=OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT,
                quantity=quantity,
                client_order_id=f"manual-{digest}",
                idempotency_key=f"manual-{digest}",
                price=price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                reduce_only=False,
                reason=synthetic_signal.reason,
                metadata={
                    "strategy": synthetic_signal.strategy_name,
                    "source": "web_manual_order",
                    "timeframe": timeframe,
                },
            )
        else:
            if not position or not position.is_open:
                self.control_plane.record("manual_order", False, "当前没有可卖出的现货持仓。")
                return
            quantity = raw_quantity if raw_quantity and raw_quantity > 0 else position.quantity
            if quantity > position.quantity + 1e-12:
                self.control_plane.record(
                    "manual_order",
                    False,
                    f"手动卖出数量超过当前持仓，最多只能卖 {position.quantity:.6f}。",
                )
                return
            quantity = round_to_step(quantity, rule.step_size)
            price = round_to_tick(raw_price, rule.tick_size) if order_type == "LIMIT" and raw_price else None
            if order_type == "LIMIT" and price is None:
                self.control_plane.record("manual_order", False, "限价单必须填写价格。")
                return
            digest = hashlib.sha256(f"manual-sell-{normalized_symbol}-{utc_now().isoformat()}-{uuid4()}".encode("utf-8")).hexdigest()[:16]
            request = OrderRequest(
                symbol=normalized_symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT,
                quantity=quantity,
                client_order_id=f"manual-{digest}",
                idempotency_key=f"manual-{digest}",
                price=price,
                stop_loss=None,
                take_profit=None,
                reduce_only=True,
                reason=f"网页手动卖出 | {analysis.get('summary') or '按当前持仓手动减仓/平仓'}",
                metadata={
                    "strategy": str(params.get("strategy") or self.config.strategy.active_strategy),
                    "source": "web_manual_order",
                    "timeframe": timeframe,
                },
            )

        try:
            order = await self.order_manager.submit_request(
                request=request,
                account=account,
                rule=rule,
                reference_price=latest_bar.close,
            )
        except ValueError as exc:
            self.control_plane.record("manual_order", False, str(exc))
            return
        except Exception as exc:
            protect_event = self.risk_manager.enter_protect_mode(
                f"网页手动下单失败，系统进入保护模式：{exc}",
                {"symbol": normalized_symbol, "side": side, "source": "web_manual_order"},
            )
            self.repository.save_risk_event(protect_event)
            self.cache.risk_events.append(protect_event)
            self.control_plane.record("manual_order", False, str(protect_event.message))
            return

        self._remember_order(order, "网页手动下单已提交")
        if order.status.value == "FILLED" and isinstance(self.adapter, PaperBroker):
            fill = self.adapter.consume_fill(order.order_id)
            if fill is not None:
                await self._handle_fill(fill)
        await self._refresh_account_state()
        side_label = "买入" if side == "BUY" else "卖出"
        self.control_plane.record(
            "manual_order",
            True,
            f"网页手动{side_label}订单已提交：{normalized_symbol} {quantity:.6f} ({order_type})。",
            {"order_id": order.order_id, "symbol": normalized_symbol, "side": side, "quantity": quantity},
        )

    async def _handle_cancel_order_command(self, params: dict[str, Any]) -> None:
        if self.config.app.mode not in {RuntimeMode.PAPER, RuntimeMode.TESTNET}:
            self.control_plane.record("cancel_order", False, "网页撤单只在仿真盘和测试盘开放。")
            return
        symbol = str(params.get("symbol") or "").strip().upper()
        order_id = str(params.get("order_id") or "").strip()
        if not symbol or not order_id:
            self.control_plane.record("cancel_order", False, "撤单时必须提供交易对和订单号。")
            return
        try:
            order = await self.adapter.cancel_order(normalize_symbol(symbol), order_id)
        except Exception as exc:
            self.control_plane.record("cancel_order", False, f"撤单失败：{exc}")
            return
        self._remember_order(order, "网页撤单已提交")
        await self._refresh_account_state()
        self.control_plane.record("cancel_order", True, f"撤单请求已提交：{order_id}")

    async def analyze_symbol(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)
        strategy_internal = resolve_strategy_name(strategy_name or self.config.strategy.active_strategy)
        latest_bar = await self._latest_or_warmup_bar(symbol, timeframe)
        if latest_bar is None:
            return {"ok": False, "message": f"{symbol} / {timeframe} 当前没有可用 K 线数据。"}

        bar_history = self.bar_histories.get((normalized_symbol, timeframe))
        if not bar_history:
            bar_history = await self.market_data_feed.warmup(symbol, timeframe, self.config.exchange.warmup_limit)
        if not bar_history:
            return {"ok": False, "message": f"{symbol} / {timeframe} 的历史数据不足，暂时无法分析。"}

        strategy = build_strategy_from_config(strategy_internal, symbol, timeframe, self.config.strategy)
        for bar in bar_history:
            strategy.on_bar(bar)

        rule = self.rule_map.get(normalized_symbol)
        if rule is None:
            all_rules = await self.adapter.get_exchange_rules()
            rule = all_rules.get(normalized_symbol)
            if rule is not None:
                self.rule_map[normalized_symbol] = rule

        account = await self._current_account_snapshot()
        positions = await self.adapter.get_positions()
        position = positions.get(normalized_symbol)
        signal = strategy.generate_signal(bar_history[-1], position)

        blocked_reasons: list[str] = []
        quantity = 0.0
        stop_loss = None
        take_profit = None
        status = "watch"
        advice = "继续观察，等待更明确的触发条件。"
        if signal.signal_type == SignalType.HOLD:
            if self._lookup_market_change(normalized_symbol) >= 12:
                advice = "当前涨幅已经不小，但策略还没给出进场确认，优先等回踩或下一轮信号，避免追高。"
        elif rule is None:
            status = "blocked"
            blocked_reasons = ["当前没有该交易对的交易规则。"]
            advice = "可以观察，但这套系统当前拿不到该交易对的完整下单规则，先不要下单。"
        else:
            decision = self.risk_manager.evaluate_signal(signal, account, position, rule, bar_history)
            quantity = decision.quantity
            stop_loss = decision.stop_loss
            take_profit = decision.take_profit
            blocked_reasons = decision.reasons
            if decision.allowed:
                status = "planned" if signal.signal_type == SignalType.BUY else "position"
                advice = (
                    "当前策略与风控都允许进场，可以考虑按计划试单。"
                    if signal.signal_type == SignalType.BUY
                    else "当前更适合按持仓管理或减仓逻辑处理，而不是再开新仓。"
                )
            else:
                status = "blocked"
                advice = f"当前不建议动手，主要是：{'；'.join(blocked_reasons)}。"

        summary = self._compose_analysis_summary(
            signal_type=signal.signal_type.value,
            status=status,
            symbol=normalized_symbol,
            timeframe=timeframe,
            blocked_reasons=blocked_reasons,
        )
        metrics = self._derive_trade_metrics(bar_history[-1].close, quantity, stop_loss, take_profit)
        return {
            "ok": True,
            "symbol": normalized_symbol,
            "display_symbol": symbol if "/" in symbol else strategy.symbol,
            "timeframe": timeframe,
            "strategy_name": strategy_internal,
            "strategy_label": strategy_public_name(strategy_internal),
            "signal_type": signal.signal_type.value,
            "status": status,
            "reason": signal.reason,
            "summary": summary,
            "advice": advice,
            "entry_price": bar_history[-1].close,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "blocked_reasons": blocked_reasons,
            "position_open": bool(position and position.is_open),
            "position_quantity": position.quantity if position else 0.0,
            "risk_budget": account.net_asset_value * self.config.risk.max_trade_risk_pct,
            "change_24h_pct": self._lookup_market_change(normalized_symbol),
            "quote_volume_24h": self._lookup_market_quote_volume(normalized_symbol),
            "mode": self.config.app.mode.value,
            **metrics,
        }

    def run_symbol_analysis_sync(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        if self.loop is None:
            return {"ok": False, "message": "交易引擎尚未完成启动，请稍等几秒再试。"}
        future = asyncio.run_coroutine_threadsafe(
            self.analyze_symbol(symbol=symbol, timeframe=timeframe, strategy_name=strategy_name),
            self.loop,
        )
        return future.result(timeout=15)

    def _mark_positions_to_market(self, positions: dict[str, Position]) -> None:
        for position in positions.values():
            if position.quantity <= 0:
                continue
            latest_price = self._latest_price_for_symbol(position.symbol)
            if latest_price is not None:
                position.update_mark(latest_price)

    def _latest_price_for_symbol(self, symbol: str) -> float | None:
        candidates = [
            bar.close
            for (bar_symbol, _timeframe), bar in self.cache.latest_bars.items()
            if bar_symbol == normalize_symbol(symbol)
        ]
        return candidates[-1] if candidates else None

    def _revalue_account_snapshot(self, snapshot: AccountSnapshot, positions: dict[str, Position]) -> AccountSnapshot:
        quote_total = snapshot.balances.get(self.config.exchange.quote_asset, Balance(asset=self.config.exchange.quote_asset, free=0.0)).total
        net_asset_value = quote_total + sum(
            position.quantity * (position.market_price or position.average_price)
            for position in positions.values()
            if position.quantity > 0
        )
        return AccountSnapshot(
            timestamp=snapshot.timestamp,
            balances=snapshot.balances,
            net_asset_value=net_asset_value,
            available_quote_balance=snapshot.available_quote_balance,
        )

    def _build_strategy(self, symbol: str, timeframe: str) -> BaseStrategy:
        return build_strategy_from_config(
            self.config.strategy.active_strategy,
            symbol,
            timeframe,
            self.config.strategy,
        )

    @staticmethod
    def _derive_trade_metrics(
        entry_price: float | None,
        quantity: float | None,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> dict[str, float | None]:
        entry = float(entry_price or 0.0)
        qty = float(quantity or 0.0)
        notional_value = entry * qty if entry > 0 and qty > 0 else 0.0
        risk_amount = 0.0
        reward_amount = 0.0
        risk_reward_ratio: float | None = None
        if entry > 0 and qty > 0 and stop_loss is not None:
            risk_amount = max(0.0, (entry - float(stop_loss)) * qty)
        if entry > 0 and qty > 0 and take_profit is not None:
            reward_amount = max(0.0, (float(take_profit) - entry) * qty)
        if risk_amount > 0 and reward_amount > 0:
            risk_reward_ratio = reward_amount / risk_amount
        return {
            "notional_value": notional_value,
            "risk_amount": risk_amount,
            "reward_amount": reward_amount,
            "risk_reward_ratio": risk_reward_ratio,
        }

    async def _latest_or_warmup_bar(self, symbol: str, timeframe: str) -> Bar | None:
        normalized_symbol = normalize_symbol(symbol)
        latest = self.cache.latest_bars.get((normalized_symbol, timeframe))
        if latest is not None:
            return latest
        history = self.bar_histories.get((normalized_symbol, timeframe), [])
        if history:
            return history[-1]
        warmup = await self.market_data_feed.warmup(symbol, timeframe, self.config.exchange.warmup_limit)
        if not warmup:
            return None
        return warmup[-1]

    async def _current_account_snapshot(self) -> AccountSnapshot:
        try:
            return await self.adapter.get_account_snapshot()
        except Exception:
            if self.cache.account_snapshot is not None:
                return self.cache.account_snapshot
            return AccountSnapshot(
                timestamp=utc_now(),
                balances={self.config.exchange.quote_asset: Balance(asset=self.config.exchange.quote_asset, free=0.0)},
                net_asset_value=0.0,
                available_quote_balance=0.0,
            )

    @staticmethod
    def _parse_optional_float(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _lookup_market_change(self, symbol: str) -> float:
        for row in self.market_board.get("rows", []):
            if row.get("symbol") == symbol:
                return float(row.get("price_change_percent", 0.0) or 0.0)
        return 0.0

    def _lookup_market_quote_volume(self, symbol: str) -> float:
        for row in self.market_board.get("rows", []):
            if row.get("symbol") == symbol:
                return float(row.get("quote_volume", 0.0) or 0.0)
        return 0.0

    @staticmethod
    def _compose_analysis_summary(
        signal_type: str,
        status: str,
        symbol: str,
        timeframe: str,
        blocked_reasons: list[str],
    ) -> str:
        if status == "planned":
            return f"{symbol} 在 {timeframe} 周期上已经给出可执行信号，可以按系统建议的止损止盈与风险预算试单。"
        if status == "position":
            return f"{symbol} 当前已有仓位，更适合做持仓管理而不是重复加仓。"
        if status == "blocked":
            reason = "；".join(blocked_reasons) if blocked_reasons else "当前条件还不满足"
            return f"{symbol} 目前不建议下手，主要原因是：{reason}。"
        if signal_type == "HOLD":
            return f"{symbol} 在 {timeframe} 周期上还没有形成明确交易边。"
        return f"{symbol} 当前更适合继续观察。"
