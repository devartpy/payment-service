import asyncio
import uuid

import httpx
import pytest
import structlog
from fastapi import FastAPI

from src.api.middlewares import TraceIdMiddleware


@pytest.fixture
def app() -> TraceIdMiddleware:
    fastapi_app = FastAPI()

    @fastapi_app.get("/trace")
    async def trace() -> dict[str, str]:
        await asyncio.sleep(0)
        return {"trace_id": structlog.contextvars.get_contextvars()["trace_id"]}

    @fastapi_app.get("/error")
    async def error() -> None:
        raise RuntimeError("test error")

    return TraceIdMiddleware(fastapi_app)


@pytest.mark.asyncio
async def test_trace_id_is_reused_or_generated(app: TraceIdMiddleware) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        incoming = await client.get("/trace", headers={"X-Trace-ID": "upstream-id"})
        generated = await client.get("/trace")

    assert incoming.headers["X-Trace-ID"] == incoming.json()["trace_id"] == "upstream-id"
    generated_id = generated.headers["X-Trace-ID"]
    assert generated.json()["trace_id"] == generated_id
    uuid.UUID(generated_id)


@pytest.mark.asyncio
async def test_trace_id_is_isolated_between_concurrent_requests(app: TraceIdMiddleware) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.get("/trace", headers={"X-Trace-ID": "first"}),
            client.get("/trace", headers={"X-Trace-ID": "second"}),
        )

    assert first.json()["trace_id"] == "first"
    assert second.json()["trace_id"] == "second"
    assert structlog.contextvars.get_contextvars() == {}


@pytest.mark.asyncio
async def test_trace_id_is_returned_on_unhandled_error(app: TraceIdMiddleware) -> None:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/error", headers={"X-Trace-ID": "failed-request"})

    assert response.status_code == 500
    assert response.headers["X-Trace-ID"] == "failed-request"
