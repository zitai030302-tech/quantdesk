from __future__ import annotations

import asyncio

import httpx

from data.rest_client import BinanceRestClient


def test_rest_client_retries_transient_errors(monkeypatch) -> None:
    attempts = {"count": 0}

    async def fake_request(self, method: str, url: str, params=None, headers=None):  # noqa: ANN001
        attempts["count"] += 1
        request = httpx.Request(method, url, params=params, headers=headers)
        if attempts["count"] < 3:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(200, request=request, json={"ok": True, "attempt": attempts["count"]})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    client = BinanceRestClient(
        base_url="https://example.com",
        retry_attempts=3,
        retry_backoff_sec=0.0,
    )

    payload = asyncio.run(client.request("GET", "/api/v3/ping"))

    assert attempts["count"] == 3
    assert payload["ok"] is True


def test_rest_client_does_not_retry_non_retryable_http_errors(monkeypatch) -> None:
    attempts = {"count": 0}

    async def fake_request(self, method: str, url: str, params=None, headers=None):  # noqa: ANN001
        attempts["count"] += 1
        request = httpx.Request(method, url, params=params, headers=headers)
        response = httpx.Response(400, request=request, json={"msg": "bad request"})
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    client = BinanceRestClient(
        base_url="https://example.com",
        retry_attempts=3,
        retry_backoff_sec=0.0,
    )

    try:
        asyncio.run(client.request("GET", "/api/v3/ping"))
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 400
    else:  # pragma: no cover - defensive
        raise AssertionError("expected HTTPStatusError")

    assert attempts["count"] == 1
