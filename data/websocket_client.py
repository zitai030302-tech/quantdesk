from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import websockets

from data.rest_client import build_ws_api_signed_params


LOGGER = logging.getLogger("data.websocket")


class ReconnectingWebSocketClient:
    def __init__(self, url: str, reconnect_delay_sec: float = 2.0) -> None:
        self.url = url
        self.reconnect_delay_sec = reconnect_delay_sec

    async def stream(self) -> AsyncIterator[dict]:
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as connection:
                    async for message in connection:
                        yield json.loads(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network dependent
                LOGGER.warning("WebSocket 连接已断开：%s", exc)
                await asyncio.sleep(self.reconnect_delay_sec)


class BinanceWebSocketApiClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        recv_window_ms: int = 5000,
        reconnect_delay_sec: float = 2.0,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window_ms = recv_window_ms
        self.reconnect_delay_sec = reconnect_delay_sec
        self.connection = None
        self._events: asyncio.Queue[dict] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        self.connection = await websockets.connect(self.url, ping_interval=20, ping_timeout=20)
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.connection:
            await self.connection.close()

    async def _reader_loop(self) -> None:
        try:
            assert self.connection is not None
            async for message in self.connection:
                payload = json.loads(message)
                response_id = str(payload.get("id")) if payload.get("id") is not None else None
                if response_id and response_id in self._pending:
                    future = self._pending.pop(response_id)
                    if not future.done():
                        future.set_result(payload)
                else:
                    await self._events.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - network dependent
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)
            await self._events.put({"event": {"e": "clientError", "message": str(exc)}})

    async def request(self, method: str, params: dict | None = None, signed: bool = False) -> dict:
        if not self.connection:
            raise RuntimeError("WebSocket API 客户端尚未连接")

        request_id = str(uuid4())
        request_params = dict(params or {})
        if signed:
            request_params = build_ws_api_signed_params(
                request_params,
                api_key=self.api_key,
                api_secret=self.api_secret,
                recv_window_ms=self.recv_window_ms,
            )

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        payload = {"id": request_id, "method": method}
        if request_params:
            payload["params"] = request_params
        await self.connection.send(json.dumps(payload))
        response = await future
        status = int(response.get("status", 200))
        if status >= 400:
            raise RuntimeError(response.get("error", {}).get("msg", f"WebSocket API 请求失败：{status}"))
        return response

    async def next_event(self) -> dict:
        return await self._events.get()
