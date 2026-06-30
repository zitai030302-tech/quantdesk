from __future__ import annotations

import math

from data.models import ExchangeRule


class PositionSizer:
    @staticmethod
    def size_from_risk(
        net_asset_value: float,
        available_quote: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
        rule: ExchangeRule,
        fee_rate: float,
        slippage_bps: float = 0.0,
    ) -> float:
        risk_amount = net_asset_value * risk_pct
        per_unit_risk = max(entry_price - stop_loss, 0.0)
        if risk_amount <= 0 or per_unit_risk <= 0:
            return 0.0
        quantity = risk_amount / per_unit_risk
        slippage_multiplier = 1 + (slippage_bps / 10_000)
        max_affordable = available_quote / (entry_price * slippage_multiplier * (1 + fee_rate))
        quantity = min(quantity, max_affordable)
        if quantity < rule.min_qty:
            return 0.0
        steps = math.floor(quantity / rule.step_size)
        normalized = steps * rule.step_size
        if normalized * entry_price < rule.min_notional:
            return 0.0
        return round(normalized, 8)
