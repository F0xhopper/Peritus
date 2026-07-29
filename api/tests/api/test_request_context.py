"""Request correlation, the error boundary, and the readiness probe.

Both chat endpoints answer a failure with a deliberately vague message — a
client must not be told what broke inside a retrieval pipeline. The request id
is what keeps that answerable: it is on the response, and it is on every log
line written while the request was in flight.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from peritus.api.middleware import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    _clean_id,
    install_error_handlers,
)
from peritus.core.logging import RequestIdFilter, current_request_id


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/ok")
    async def ok():
        return {"request_id": current_request_id()}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("the database caught fire")

    @app.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.get("/throttled")
    async def throttled():
        raise HTTPException(status_code=429, detail="slow down", headers={"Retry-After": "30"})

    return app


@pytest.fixture
async def client(app):
    # raise_app_exceptions=False because Starlette's ServerErrorMiddleware
    # re-raises after the 500 response is sent, so a real server can log it.
    # Without this the transport surfaces the exception instead of the response
    # the client would actually receive.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        yield c


# ── id generation and sanitisation ──


def test_generates_an_id_when_none_is_supplied():
    assert len(_clean_id(None)) == 16
    assert _clean_id(None) != _clean_id(None)


def test_honours_a_caller_supplied_id():
    assert _clean_id("trace-abc.123:9") == "trace-abc.123:9"


def test_strips_unsafe_characters_from_a_supplied_id():
    """The header is attacker-controlled and ends up in log lines."""
    assert _clean_id("abc\ndef INJECTED") == "abcdefINJECTED"


def test_caps_the_length_of_a_supplied_id():
    assert len(_clean_id("x" * 500)) == 64


def test_falls_back_when_a_supplied_id_sanitises_to_nothing():
    assert len(_clean_id("!!!  \n")) == 16


# ── the middleware ──


async def test_response_carries_the_request_id(client):
    resp = await client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers[REQUEST_ID_HEADER]
    # The id the handler saw is the id the client is told about.
    assert resp.json()["request_id"] == resp.headers[REQUEST_ID_HEADER]


async def test_inbound_id_spans_the_hop(client):
    resp = await client.get("/ok", headers={REQUEST_ID_HEADER: "edge-42"})
    assert resp.headers[REQUEST_ID_HEADER] == "edge-42"
    assert resp.json()["request_id"] == "edge-42"


async def test_context_does_not_leak_between_requests(client):
    first = await client.get("/ok", headers={REQUEST_ID_HEADER: "first"})
    second = await client.get("/ok")
    assert first.json()["request_id"] == "first"
    assert second.json()["request_id"] != "first"


async def test_concurrent_requests_get_distinct_ids(client):
    responses = await asyncio.gather(*[
        client.get("/ok", headers={REQUEST_ID_HEADER: f"req-{i}"}) for i in range(8)
    ])
    assert [r.json()["request_id"] for r in responses] == [f"req-{i}" for i in range(8)]


# ── the error boundary ──


async def test_unhandled_exception_becomes_a_traceable_500(client):
    resp = await client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["request_id"] == resp.headers[REQUEST_ID_HEADER]
    assert body["request_id"] != "-", "a 500 with no id is exactly the case this exists for"
    # The internal detail must not reach the client.
    assert "database caught fire" not in resp.text


async def test_a_500_keeps_the_id_the_caller_sent(client):
    """The regression: ServerErrorMiddleware runs *outside* the request-context
    middleware, so a ContextVar already reset in its ``finally`` reads "-" by the
    time the catch-all handler builds the response. The id has to come from the
    ASGI scope, which survives."""
    resp = await client.get("/boom", headers={REQUEST_ID_HEADER: "trace-me"})

    assert resp.status_code == 500
    assert resp.headers[REQUEST_ID_HEADER] == "trace-me"
    assert resp.json()["request_id"] == "trace-me"


async def test_unhandled_exception_is_logged_against_its_id(client, caplog):
    # setup_logging installs the filter on the real handlers; caplog brings its
    # own, so attach it here to observe what a deployed handler would see.
    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.ERROR, logger="peritus.api.middleware"):
        resp = await client.get("/boom", headers={REQUEST_ID_HEADER: "trace-me"})

    assert any("the database caught fire" in (r.exc_text or "") for r in caplog.records)
    # Every record written while handling the request carries the same id the
    # client was given, which is the whole point of the correlation.
    for record in caplog.records:
        assert getattr(record, "request_id", None) == "trace-me"
    assert resp.headers[REQUEST_ID_HEADER] == "trace-me"


async def test_http_exception_detail_is_preserved(client):
    """Author-written detail — including the entitlement payloads — passes through."""
    resp = await client.get("/teapot")
    assert resp.status_code == 418
    assert resp.json()["detail"] == "I'm a teapot"
    assert resp.json()["request_id"]


async def test_http_exception_headers_survive_the_handler(client):
    """Retry-After on a 429 is the whole point of the throttle's response."""
    resp = await client.get("/throttled")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "30"
    assert resp.headers[REQUEST_ID_HEADER]


# ── streaming must survive the middleware ──


async def test_sse_streams_incrementally(app):
    """Three of this API's endpoints are long-lived SSE streams. A middleware
    that buffers the body turns a live build log into one delivery at the end.

    Driven against the ASGI app directly: httpx's ASGITransport collects the
    whole body before returning, so it cannot observe incremental delivery at
    all (attempting it deadlocks against the gate below).
    """
    from starlette.responses import StreamingResponse

    gate = asyncio.Event()

    async def body():
        yield b"data: first\n\n"
        await gate.wait()
        yield b"data: second\n\n"

    @app.get("/stream")
    async def stream():
        return StreamingResponse(body(), media_type="text/event-stream")

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "path": "/stream", "raw_path": b"/stream",
        "query_string": b"", "root_path": "", "scheme": "http",
        "headers": [(b"host", b"test")], "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    sent: list[dict] = []
    first_chunk = asyncio.Event()
    disconnect = asyncio.Event()
    body_sent = False

    async def receive():
        # A real server sends the request body once and then blocks until the
        # client disconnects. Returning immediately every time busy-spins
        # StreamingResponse's disconnect listener and starves the event loop.
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(first_chunk.wait(), timeout=5)

    # The first chunk reached the transport while the generator is still
    # suspended — nothing downstream is waiting for the body to complete.
    assert not gate.is_set()
    assert not task.done()
    start = sent[0]
    assert start["type"] == "http.response.start"
    assert any(k.lower() == b"x-request-id" for k, _ in start["headers"])
    assert sent[1]["body"] == b"data: first\n\n"

    gate.set()
    await asyncio.wait_for(task, timeout=5)
    assert b"data: second\n\n" in b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )


async def test_receive_channel_is_passed_through_untouched(app):
    """``_tail_events`` polls ``request.is_disconnected()`` to stop tailing a
    build when the client goes away; that reads the ASGI receive channel.
    BaseHTTPMiddleware substitutes it — a plain ASGI middleware must not.
    """
    seen = {}

    @app.get("/receive")
    async def receive_probe(request: Request):
        seen["receive"] = request.receive
        # The call must work, not hang or raise, for disconnect polling to work.
        seen["disconnected"] = await request.is_disconnected()
        return {"ok": True}

    captured_receive = {}

    class _Probe:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            captured_receive["outer"] = receive
            await self.app(scope, receive, send)

    app.add_middleware(_Probe)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/receive")

    assert resp.status_code == 200
    assert seen["disconnected"] is False
    assert seen["receive"] is captured_receive["outer"], (
        "the receive channel was replaced — disconnect detection is unreliable"
    )


# ── the logging filter ──


def test_filter_stamps_the_current_id_on_a_record():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "msg", None, None)
    RequestIdFilter().filter(record)
    # Outside a request the id reads as "-", so third-party records still format.
    assert record.request_id == "-"


def test_log_format_renders_records_from_any_logger():
    from peritus.core.logging import _LOG_FORMAT

    record = logging.LogRecord("httpx", logging.INFO, "f", 1, "hello", None, None)
    RequestIdFilter().filter(record)
    assert "[-]" in logging.Formatter(_LOG_FORMAT).format(record)


# ── readiness ──


@pytest.fixture
def health_app():
    from peritus.api.routes import health

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    return app


@pytest.fixture
async def health_client(health_app):
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as c:
        yield c


def _pool_that(acquire_side_effect=None, conn=None):
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn or AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    if acquire_side_effect is not None:
        pool.acquire = MagicMock(side_effect=acquire_side_effect)
    else:
        pool.acquire = MagicMock(return_value=cm)
    return pool


async def test_liveness_touches_nothing(health_client):
    """/health must answer even when the database is gone, or a DB blip
    restarts every healthy process."""
    with patch("peritus.api.routes.health.get_pool", side_effect=RuntimeError("no pool")):
        resp = await health_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_reports_the_vector_index_state(health_client):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    with patch("peritus.api.routes.health.get_pool", return_value=_pool_that(conn=conn)), \
         patch("peritus.api.routes.health.halfvec_supported", return_value=True):
        resp = await health_client.get("/ready")

    assert resp.status_code == 200
    assert resp.json()["vector_index"] == "halfvec"


async def test_readiness_flags_a_missing_vector_index(health_client):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    with patch("peritus.api.routes.health.get_pool", return_value=_pool_that(conn=conn)), \
         patch("peritus.api.routes.health.halfvec_supported", return_value=False):
        resp = await health_client.get("/ready")

    assert resp.json()["vector_index"] == "none"


async def test_readiness_503s_on_an_exhausted_pool_instead_of_hanging(health_client, monkeypatch):
    """The regression: an unbounded acquire makes the probe hang, and a hanging
    probe reads as "still checking" — so the balancer keeps sending traffic."""
    from peritus.core.config import settings

    monkeypatch.setattr(settings, "DB_ACQUIRE_TIMEOUT", 0.05)

    class _NeverAcquires:
        async def __aenter__(self):
            await asyncio.sleep(3600)

        async def __aexit__(self, *exc):
            return False

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_NeverAcquires())

    with patch("peritus.api.routes.health.get_pool", return_value=pool):
        resp = await asyncio.wait_for(health_client.get("/ready"), timeout=5)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database connection pool exhausted"


async def test_readiness_503s_when_the_query_fails(health_client):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=OSError("connection reset"))
    with patch("peritus.api.routes.health.get_pool", return_value=_pool_that(conn=conn)):
        resp = await health_client.get("/ready")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database not ready"
