import pytest
from httpx import ASGITransport, AsyncClient
from starlette.types import Receive, Scope, Send

from src.api.schemas import ErrorResponse
from src.core.middleware import PlainTextErrorResponseMiddleware


async def small_plaintext_error_app(_: Scope, __: Receive, send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"Invalid host header"})


async def oversized_streamed_plaintext_error_app(
    _: Scope, __: Receive, send: Send
) -> None:
    chunks = (b"a" * 4096, b"b" * 4096, b"c")
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": chunks[0], "more_body": True})
    await send({"type": "http.response.body", "body": chunks[1], "more_body": True})
    await send({"type": "http.response.body", "body": chunks[2]})


async def non_utf8_plaintext_error_app(_: Scope, __: Receive, send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"Invalid: \xff"})


async def mixed_case_plaintext_error_app(_: Scope, __: Receive, send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [(b"content-type", b"Text/Plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": b"Invalid request"})


@pytest.mark.anyio
async def test_small_plaintext_error_is_converted_to_error_response() -> None:
    app = PlainTextErrorResponseMiddleware(small_plaintext_error_app)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert (
        response.json()
        == ErrorResponse(
            detail="Invalid host header", request_id="unknown"
        ).model_dump()
    )


@pytest.mark.anyio
async def test_oversized_streamed_plaintext_error_is_passed_through() -> None:
    app = PlainTextErrorResponseMiddleware(oversized_streamed_plaintext_error_app)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 500
    assert response.headers["content-type"] == "text/plain"
    assert response.content == b"a" * 4096 + b"b" * 4096 + b"c"


@pytest.mark.anyio
async def test_non_utf8_plaintext_error_is_converted_to_error_response() -> None:
    app = PlainTextErrorResponseMiddleware(non_utf8_plaintext_error_app)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 400
    assert (
        response.json()
        == ErrorResponse(detail="Invalid: \ufffd", request_id="unknown").model_dump()
    )


@pytest.mark.anyio
async def test_plaintext_media_type_is_matched_case_insensitively() -> None:
    app = PlainTextErrorResponseMiddleware(mixed_case_plaintext_error_app)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert (
        response.json()
        == ErrorResponse(detail="Invalid request", request_id="unknown").model_dump()
    )


@pytest.mark.anyio
async def test_stream_failure_does_not_send_second_response_or_leak_exception():
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from src.core.middleware import UnhandledErrorMiddleware

    messages = []
    handled = []

    async def broken_stream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        raise ValueError("private-measurement")

    async def handler(request: Request, error: Exception):
        handled.append(type(error).__name__)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    app = UnhandledErrorMiddleware(broken_stream, handler)
    with pytest.raises(
        RuntimeError, match="Response failed after headers were sent"
    ) as caught:
        await app({"type": "http"}, receive, send)

    import traceback

    assert "private-measurement" not in "".join(
        traceback.format_exception(caught.value)
    )
    assert handled == ["ValueError"]
    assert [
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    ] == [200]
