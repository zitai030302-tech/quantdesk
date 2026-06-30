from __future__ import annotations

import logging

from data.models import RiskEvent


LOGGER = logging.getLogger("app.alerts")


class ConsoleAlerter:
    def notify(self, title: str, message: str) -> None:
        LOGGER.warning("%s | %s", title, message)

    def notify_risk_event(self, event: RiskEvent) -> None:
        LOGGER.warning("risk event | %s | %s", event.event_type, event.message)
