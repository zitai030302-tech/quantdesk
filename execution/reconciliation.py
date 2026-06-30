from __future__ import annotations

from data.models import OrderRecord


def reconcile_orders(local_orders: dict[str, OrderRecord], remote_orders: dict[str, OrderRecord]) -> list[str]:
    mismatches: list[str] = []
    for order_id, local in local_orders.items():
        remote = remote_orders.get(order_id)
        if remote is None:
            mismatches.append(f"远端订单缺失：{order_id}")
            continue
        if local.status != remote.status:
            mismatches.append(
                f"订单状态不一致：{order_id}，本地={local.status.value}，远端={remote.status.value}"
            )
    return mismatches
