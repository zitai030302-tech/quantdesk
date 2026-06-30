from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx


def sign_hmac_payload(payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_ws_api_signed_params(
    params: dict | None,
    api_key: str,
    api_secret: str,
    recv_window_ms: int,
    timestamp_ms: int | None = None,
) -> dict:
    payload = dict(params or {})
    payload["apiKey"] = api_key
    payload.setdefault("timestamp", timestamp_ms or int(time.time() * 1000))
    payload.setdefault("recvWindow", recv_window_ms)
    signature_payload = "&".join(
        f"{key}={payload[key]}"
        for key in sorted(payload)
    )
    payload["signature"] = sign_hmac_payload(signature_payload, api_secret)
    return payload


class BinanceRestClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout_sec: float = 10.0,
        recv_window_ms: int = 5000,
        retry_attempts: int = 3,
        retry_backoff_sec: float = 0.75,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout_sec = timeout_sec
        self.recv_window_ms = recv_window_ms
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_sec = max(0.0, retry_backoff_sec)

    def _request_url(self, path: str) -> str:
        base = self.base_url
        if base.endswith("/api") and path.startswith("/api/"):
            base = base[:-4]
        if base.endswith("/api/v3") and path.startswith("/api/v3"):
            base = base[:-7]
        return f"{base}{path}"

    async def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
    ) -> dict | list:
        params = dict(params or {})
        headers = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv_window_ms
            query = urlencode(params, doseq=True)
            signature = sign_hmac_payload(query, self.api_secret)
            params["signature"] = signature
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            last_error: Exception | None = None
            for attempt in range(self.retry_attempts):
                try:
                    response = await client.request(method, self._request_url(path), params=params, headers=headers)
                    response.raise_for_status()
                    return response.json()
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    last_error = exc
                    is_retryable_status = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {408, 409, 418, 429, 500, 502, 503, 504}
                    is_retryable = isinstance(exc, httpx.RequestError) or is_retryable_status
                    if attempt >= self.retry_attempts - 1 or not is_retryable:
                        raise
                    await asyncio.sleep(self.retry_backoff_sec * (attempt + 1))
            if last_error is not None:
                raise last_error
            raise RuntimeError("request retry loop exited unexpectedly")
