from __future__ import annotations

from data.models import ExchangeRule


def extract_symbol_rules(exchange_info: dict) -> dict[str, ExchangeRule]:
    rules: dict[str, ExchangeRule] = {}
    for item in exchange_info.get("symbols", []):
        if item.get("status") != "TRADING":
            continue
        lot_size = next((flt for flt in item.get("filters", []) if flt.get("filterType") == "LOT_SIZE"), {})
        price_filter = next((flt for flt in item.get("filters", []) if flt.get("filterType") == "PRICE_FILTER"), {})
        min_notional_filter = next(
            (
                flt
                for flt in item.get("filters", [])
                if flt.get("filterType") in {"MIN_NOTIONAL", "NOTIONAL"}
            ),
            {},
        )
        symbol = item["symbol"]
        rules[symbol] = ExchangeRule(
            symbol=symbol,
            tick_size=float(price_filter.get("tickSize", 0.01)),
            step_size=float(lot_size.get("stepSize", 0.0001)),
            min_qty=float(lot_size.get("minQty", 0.0001)),
            min_notional=float(
                min_notional_filter.get("minNotional")
                or min_notional_filter.get("notional")
                or 10.0
            ),
            base_asset=item.get("baseAsset", symbol[:-4]),
            quote_asset=item.get("quoteAsset", "USDT"),
        )
    return rules
