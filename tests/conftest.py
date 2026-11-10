"""Shared pytest fixtures: hermetic upstream, no politeness delay, a fresh cache per test."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fixture_routes import resolve

from vgi_soccer import api


@pytest.fixture(autouse=True)
def _fresh_client_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SOCCER_MIN_REQUEST_INTERVAL", "0")
    api.clear_cache()
    yield
    api.clear_cache()


def _handler(request: httpx.Request) -> httpx.Response:
    query = {key: value for key, value in request.url.params.items()}
    payload = resolve(request.url.path, query)
    if payload is None:
        return httpx.Response(404, json={"code": 404, "message": "not found"})
    return httpx.Response(
        200,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Cache-Control": "max-age=120"},
    )


@pytest.fixture
def fixture_upstream(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    """Route the shared HTTP client to recorded fixtures; yields the request log."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _handler(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(api, "_shared_client", client)
    yield requests
    client.close()
