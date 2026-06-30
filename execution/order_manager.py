from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import uuid4

from app.types import ExecutionConfig
from data.models import AccountSnapshot, Bar, ExchangeRule, OrderRecord, OrderRequest, OrderType, Position, Side, Signal, SignalType
from execution.adapter_base import ExchangeAdapter
from risk.manager import RiskDecision, RiskManager


LOGGER = logging.getLogger("execution.order_manager")


class OrderManager:
    def __init__(
        self,
        adapter: ExchangeAdapter,
        risk_manager: RiskManager,
        execution_config: ExecutionConfig,
    ) -> None:
        self.adapter = adapter
        self.risk_manager = risk_manager
        self.execution_config = execution_config
        self.idempotency_keys: set[str] = set()

    async def handle_signal(
        self,
        signal: Signal,
        account: AccountSnapshot,
        position: Position | None,
        rule: ExchangeRule,
        bar_history: list[Bar],
    ) -> tuple[OrderRecord | None, list[str]]:
        decision = self.risk_manager.evaluate_signal(signal, account, position, rule, bar_history)
        if not decision.allowed:
            return None, decision.reasons

        request = self._build_request(signal, decision, bar_history[-1].close)
        try:
            order = await self.submit_request(
                request=request,
                account=account,
                rule=rule,
                reference_price=bar_history[-1].close,
            )
        except ValueError as exc:
            return None, str(exc).split("；")
        return order, []

    async def submit_request(
        self,
        request: OrderRequest,
        account: AccountSnapshot,
        rule: ExchangeRule,
        reference_price: float,
    ) -> OrderRecord:
        if request.idempotency_key in self.idempotency_keys:
            raise ValueError("检测到重复的幂等请求键")

        from execution.validators import validate_order_request

        validation_errors = validate_order_request(
            request=request,
            rule=rule,
            account=account,
            reference_price=reference_price,
            slippage_bps=self.risk_manager.config.slippage_bps,
            fee_rate=self.execution_config.fee_rate,
        )
        if validation_errors:
            raise ValueError("；".join(validation_errors))

        self.idempotency_keys.add(request.idempotency_key)
        return await self._submit_with_retries(request, reference_price)

    def _build_request(self, signal: Signal, decision: RiskDecision, last_close: float) -> OrderRequest:
        side = Side.BUY if signal.signal_type == SignalType.BUY else Side.SELL
        digest = hashlib.sha256(f"{signal.strategy_name}-{signal.symbol}-{signal.timestamp.isoformat()}-{signal.signal_type.value}".encode("utf-8")).hexdigest()[:16]
        return OrderRequest(
            symbol=signal.symbol.replace("/", "").upper(),
            side=side,
            order_type=OrderType.MARKET if self.execution_config.default_order_type == "market" else OrderType.LIMIT,
            quantity=decision.quantity,
            client_order_id=f"{signal.strategy_name[:8]}-{digest}",
            idempotency_key=digest,
            price=last_close if self.execution_config.default_order_type != "market" else None,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            reduce_only=side == Side.SELL,
            reason=signal.reason,
            metadata={"strategy": signal.strategy_name},
        )

    async def _submit_with_retries(self, request: OrderRequest, reference_price: float) -> OrderRecord:
        attempts = max(self.execution_config.retry_attempts, 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if request.order_type == OrderType.MARKET:
                    return await self.adapter.place_market_order(request, reference_price)
                return await self.adapter.place_limit_order(request, reference_price)
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc
                LOGGER.warning("order submission failed on attempt %s/%s: %s", attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(self.execution_config.retry_backoff_sec * attempt)
        raise RuntimeError(f"订单在多次重试后仍提交失败：{last_error}") from last_error
