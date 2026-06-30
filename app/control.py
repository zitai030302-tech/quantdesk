from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Lock
from typing import Any
from uuid import uuid4

from strategies.registry import list_strategy_specs


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True)
class ControlCommand:
    command_id: str
    action: str
    params: dict[str, Any]
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ControlEvent:
    timestamp: datetime
    action: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ControlPlane:
    def __init__(self) -> None:
        self._queue: Queue[ControlCommand] = Queue()
        self._events: deque[ControlEvent] = deque(maxlen=20)
        self._lock = Lock()

    def submit(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        command = ControlCommand(
            command_id=str(uuid4()),
            action=str(action or "").strip().lower(),
            params=dict(params or {}),
        )
        self._queue.put(command)
        return {
            "accepted": True,
            "command_id": command.command_id,
            "message": "控制指令已加入队列，等待引擎处理。",
        }

    def drain(self) -> list[ControlCommand]:
        commands: list[ControlCommand] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except Empty:
                break
        return commands

    def record(self, action: str, success: bool, message: str, details: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._events.appendleft(
                ControlEvent(
                    timestamp=utc_now(),
                    action=action,
                    success=success,
                    message=message,
                    details=dict(details or {}),
                )
            )

    def describe(self) -> dict[str, Any]:
        with self._lock:
            events = [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "action": event.action,
                    "success": event.success,
                    "message": event.message,
                    "details": event.details,
                }
                for event in self._events
            ]
        return {
            "supported_actions": [
                {"action": "pause", "label": "暂停交易"},
                {"action": "resume", "label": "恢复交易"},
                {"action": "switch_strategy", "label": "切换策略"},
                {"action": "manual_order", "label": "网页手动下单"},
                {"action": "cancel_order", "label": "网页撤单"},
            ],
            "supported_strategies": [
                {
                    "internal": item.internal_name,
                    "public": item.public_name,
                    "description": item.description,
                }
                for item in list_strategy_specs()
            ],
            "pending_count": self._queue.qsize(),
            "events": events,
        }
