"""HTTP middleware for request trace IDs."""

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.common.logger import get_default_trace_id

logger = structlog.get_logger(__name__)


X_TRACE_ID_HEADER = "X-Trace-ID"


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        structlog.contextvars.clear_contextvars()
        incoming_trace_id = Headers(scope=scope).get(X_TRACE_ID_HEADER)
        trace_id = incoming_trace_id if incoming_trace_id is not None else get_default_trace_id()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[X_TRACE_ID_HEADER] = trace_id
            await send(message)

        try:
            logger.info("Incoming HTTP request", method=scope["method"], path=scope["path"])
            await self.app(scope, receive, send_with_trace_id)
        finally:
            structlog.contextvars.clear_contextvars()
