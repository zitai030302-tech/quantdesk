from __future__ import annotations

import math

from data.models import AccountSnapshot, ExchangeRule, OrderRequest, Side


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    rounded = math.floor(value / step) * step
    return round(rounded, 8)


def round_to_tick(value: float, tick: float) -> float:
    if tick <= 0:
        return value
    rounded = math.floor(value / tick) * tick
    return round(rounded, 8)


def validate_order_request(
    request: OrderRequest,
    rule: ExchangeRule,
    account: AccountSnapshot,
    reference_price: float,
    slippage_bps: float,
    fee_rate: float = 0.0,
) -> list[str]:
    reasons: list[str] = []
    normalized_qty = round_to_step(request.quantity, rule.step_size)
    if normalized_qty < rule.min_qty:
        reasons.append("下单数量低于最小下单量")
    notional = normalized_qty * (request.price or reference_price)
    if notional < rule.min_notional:
        reasons.append("下单名义价值低于交易所最小要求")

    if request.side == Side.BUY:
        expected_fill = reference_price * (1 + slippage_bps / 10_000)
        expected_cost = normalized_qty * expected_fill * (1 + fee_rate)
        if expected_cost > account.available_quote_balance:
            reasons.append("可用报价资产余额不足")
    return reasons
