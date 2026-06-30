from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable


LOGGER = logging.getLogger("app.supervisor")


class Supervisor:
    async def run(self, *coroutines: Awaitable[None]) -> None:
        async with asyncio.TaskGroup() as task_group:
            for coroutine in coroutines:
                task_group.create_task(coroutine)

    @staticmethod
    async def sleep_forever() -> None:
        while True:
            await asyncio.sleep(60)
