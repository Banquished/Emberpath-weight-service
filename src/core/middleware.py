import json
import logging
import re
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.logging import request_id_context

logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MAX_PLAINTEXT_ERROR_RESPONSE_BODY_BYTES = 8 * 1024


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("X-Request-ID", "")
        if not REQUEST_ID_PATTERN.fullmatch(request_id):
            request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started_at = perf_counter()
        status_code: int | None = None

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            if status_code is None:
                status_code = 500
            raise
        finally:
            if status_code is not None:
                logger.info(
                    "request_completed",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status_code": status_code,
                        "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                    },
                )
            request_id_context.reset(token)


class PlainTextErrorResponseMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_start: Message | None = None
        response_body = bytearray()

        async def send_with_error_response(message: Message) -> None:
            nonlocal response_start
            if message["type"] == "http.response.start":
                content_type = Headers(scope=message).get("content-type", "")
                media_type = content_type.partition(";")[0].strip().lower()
                if message["status"] >= 400 and media_type == "text/plain":
                    response_start = message
                    return
            elif response_start is not None and message["type"] == "http.response.body":
                body_chunk = message.get("body", b"")
                if (
                    message.get("more_body", False)
                    or len(response_body) + len(body_chunk)
                    > MAX_PLAINTEXT_ERROR_RESPONSE_BODY_BYTES
                ):
                    await send(response_start)
                    await send(message)
                    response_start = None
                    response_body.clear()
                    return

                response_body.extend(body_chunk)
                if not message.get("more_body", False):
                    request_id = scope.get("state", {}).get("request_id", "unknown")
                    detail = (
                        response_body.decode("utf-8", errors="replace")
                        or "Request failed"
                    )
                    body = json.dumps(
                        {"detail": detail, "request_id": request_id}
                    ).encode("utf-8")
                    headers = MutableHeaders(scope=response_start)
                    headers["content-type"] = "application/json"
                    headers["content-length"] = str(len(body))
                    await send(response_start)
                    await send({"type": "http.response.body", "body": body})
                    response_start = None
                return
            await send(message)

        await self.app(scope, receive, send_with_error_response)


class UnhandledErrorMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        handler: Callable[[Request, Exception], Awaitable[Response]],
    ) -> None:
        self.app = app
        self.handler = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception as error:
            response = await self.handler(Request(scope), error)
            if response_started:
                # Abort streaming without forwarding private exception details to Uvicorn.
                raise RuntimeError("Response failed after headers were sent") from None
            await response(scope, receive, send)
