from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.types import RiskStatus


@dataclass(slots=True)
class ProtectModeState:
    status: RiskStatus = RiskStatus.ACTIVE
    reason: str = ""
    since: datetime | None = None

    def activate(self, reason: str, when: datetime) -> None:
        self.status = RiskStatus.PROTECT
        self.reason = reason
        self.since = when

    def pause(self, reason: str, when: datetime) -> None:
        self.status = RiskStatus.PAUSED
        self.reason = reason
        self.since = when

    def clear(self) -> None:
        self.status = RiskStatus.ACTIVE
        self.reason = ""
        self.since = None
