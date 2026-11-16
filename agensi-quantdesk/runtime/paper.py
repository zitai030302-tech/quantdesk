"""One bounded, offline paper scenario with a persistent audit trail."""
import hashlib
import math
from pathlib import Path

from .core.data.models import OrderRequest, OrderType, Side
from .core.data.repositories import TradingRepository
from .core.data.sqlite import SQLiteStorage
from .core.execution.paper_broker import PaperBroker
from .core.execution.validators import round_to_step, validate_order_request
from .inputs import fields, number, symbol_rule
from .reports import json_text


def scenario(request):
    fields(request, allowed={"symbol", "orders", "initial_cash", "max_position_value", "fee_bps", "slippage_bps"},
           required={"symbol", "orders", "max_position_value"}, label="paper request")
    rule = symbol_rule(request["symbol"])
    cash = number(request.get("initial_cash", 10000), 1, 1e10, "initial_cash")
    cap = number(request["max_position_value"], 1, 1e12, "max_position_value")
    fee = number(request.get("fee_bps", 10), 0, 200, "fee_bps")
    slippage = number(request.get("slippage_bps", 5), 0, 200, "slippage_bps")
    orders = request["orders"]
    if not isinstance(orders, list) or not 1 <= len(orders) <= 100:
        raise ValueError("paper request needs 1 to 100 market-order intents")
    intents = []
    for item in orders:
        fields(item, allowed={"side", "quantity", "price"}, required={"side", "quantity", "price"}, label="paper order")
        if item["side"] not in ("buy", "sell"):
            raise ValueError("paper order side must be buy or sell")
        intents.append((Side(item["side"].upper()), number(item["quantity"], rule.min_qty, 1e12, "quantity"),
                        number(item["price"], 1e-10, 1e12, "price")))
    effective = {"symbol": request["symbol"], "quote_asset": rule.quote_asset, "initial_cash": cash,
                 "max_position_value": cap, "fee_bps": fee, "slippage_bps": slippage}
    return rule, effective, intents


async def run(request, output: Path):
    rule, settings, intents = scenario(request)
    fee, slippage = settings["fee_bps"] / 10_000, settings["slippage_bps"]
    broker = PaperBroker({rule.symbol: rule}, settings["initial_cash"], fee, slippage, rule.quote_asset)
    executed = []
    events = []
    for index, (side, quantity, price) in enumerate(intents, 1):
        order_request = OrderRequest(rule.symbol, side, OrderType.MARKET, quantity,
                                     f"paper-{index}", f"paper-{index}", reduce_only=(side == Side.SELL))
        account = await broker.get_account_snapshot()
        position = broker.positions.get(rule.symbol)
        held = position.quantity if position else 0
        qty = round_to_step(quantity, rule.step_size)
        reasons = validate_order_request(order_request, rule, account, price, slippage, fee)
        if side == Side.BUY and (held + qty) * price * (1 + slippage / 10_000) > settings["max_position_value"]:
            reasons.append("max_position_value")
        if side == Side.SELL and qty > held and not math.isclose(qty, held, rel_tol=0, abs_tol=1e-10):
            reasons.append("insufficient_inventory")
        row = {"intent": index, "side": side.value.lower(), "requested_qty": quantity, "quantity": qty,
               "reference_price": price, "status": "rejected" if reasons else "filled",
               "fill_price": None, "fee": None, "reasons": " | ".join(reasons)}
        if not reasons:
            order = await broker.place_market_order(order_request, price)
            fill = broker.consume_fill(order.order_id)
            row.update(fill_price=fill.price, fee=fill.fee)
            executed.append((order, fill))
        events.append(row)

    # Mark the remaining inventory at the last supplied scenario reference.
    position = broker.positions.get(rule.symbol)
    if position:
        position.update_mark(intents[-1][2])
    final = await broker.get_account_snapshot()
    report = {"mode": "paper", "assumptions": settings,
              "request_sha256": hashlib.sha256(json_text(request).encode("utf-8")).hexdigest(),
              "ending_cash": final.available_quote_balance, "ending_equity": final.net_asset_value,
              "position_quantity": position.quantity if position else 0.0,
              "total_fees": sum(fill.fee for _, fill in executed),
              "filled": len(executed), "rejected": len(events) - len(executed), "events": events}
    storage = SQLiteStorage(output / "paper.sqlite3")
    try:
        storage.initialize()
        repository = TradingRepository(storage)
        for order, fill in executed:
            repository.save_order(order)
            repository.save_fill(fill)
        if position:
            repository.save_position(position)
        storage.execute("CREATE TABLE paper_scenario (id INTEGER PRIMARY KEY, report_json TEXT NOT NULL)")
        storage.execute("INSERT INTO paper_scenario VALUES (1, ?)", (json_text(report),))
    finally:
        storage.close()
    return report, {"paper": (tuple(events[0]), events)}
