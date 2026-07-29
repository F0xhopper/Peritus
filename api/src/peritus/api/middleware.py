"""Request correlation and the last-resort error boundary.

**Why an id.** Both chat endpoints stream over SSE and answer a failure with a
deliberately vague ``{"type": "error"}`` frame — a client must not be told what
broke inside a retrieval pipeline. That is right, but it left nothing connecting
a user saying "it failed at 14:32" to the traceback that explains it. Every
request now carries an id: it is stamped on every log record emitted while
handling that request (see :class:`peritus.core.logging.RequestIdFilter`),
returned in the ``X-Request-ID`` response header, and included in error bodies.

An inbound ``X-Request-ID`` is honoured so a proxy's or client's id wins and one
identifier spans the whole hop. It is length-capped and character-filtered — it
ends up in log lines, and a request header is attacker-controlled.

**Why a handler.** Without one, an unhandled exception becomes a bare 500 with
no log line of our own and no id. The handler below logs the traceback against
the request id and returns a stable JSON shape, so every 500 is traceable to
exactly one server-side event.
"""

import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from peritus.core.logging import current_request_id, get_logger, request_id_var

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_ID_LENGTH = 64
_ID_SAFE = re.compile(r"[^A-Za-z0-9._:-]")


def _clean_id(raw: str | None) -> str:
    if not raw:
        return uuid.uuid4().hex[:16]
    cleaned = _ID_SAFE.sub("", raw)[:_MAX_ID_LENGTH]
    return cleaned or uuid.uuid4().hex[:16]


def _request_id(request: Request) -> str:
    """The id for this request, resolved for use inside an exception handler.

    ``request.state`` is the authority, not the ContextVar. Starlette's
    ``ServerErrorMiddleware`` — which runs the catch-all handler below — sits
    *outside* this middleware, so by the time an unhandled exception reaches it
    the ContextVar has already been reset and reads ``-``. State lives in the
    ASGI scope and survives, so the 500 a client receives carries the same id as
    the log line written on the way out.

    The fallback path (an error raised before this middleware ran, e.g. in CORS)
    mints an id and binds it, so the handler's own log line and the response body
    still agree on one identifier.
    """
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id
    request_id = current_request_id()
    if request_id != "-":
        return request_id
    request_id = _clean_id(None)
    request_id_var.set(request_id)
    request.state.request_id = request_id
    return request_id


class RequestContextMiddleware:
    """Bind a request id for the duration of the request and log unhandled errors.

    Written as raw ASGI rather than as a ``BaseHTTPMiddleware`` subclass, and
    that matters here specifically. ``BaseHTTPMiddleware`` runs the downstream
    app in a separate task and pipes the response through a memory stream,
    substituting its own ``receive`` channel. Three of this API's endpoints are
    long-lived SSE streams, and one of them (``_tail_events``) polls
    ``request.is_disconnected()`` — which reads that channel — to decide when to
    stop tailing a build. Intercepting it risks a build log that streams late or
    never notices the client has gone. A plain ASGI callable passes ``receive``
    through untouched and only decorates the response-start message.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _clean_id(_header(scope, REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        # Into the scope, not just the ContextVar: the scope survives out to
        # ServerErrorMiddleware, which runs the catch-all handler. See _request_id.
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "Unhandled error: %s %s after %.0fms",
                scope.get("method", "?"), scope.get("path", "?"), elapsed_ms,
            )
            raise
        finally:
            request_id_var.reset(token)


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("latin-1")
    return None


def install_error_handlers(app: FastAPI) -> None:
    """Uniform JSON error bodies, each carrying the request id."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # HTTPException detail is deliberate, author-written text (or, for
        # entitlement denials, a structured payload) — pass it through as-is.
        request_id = _request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers={**(exc.headers or {}), REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        request_id = _request_id(request)
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_errors(exc), "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request_id = _request_id(request)
        # Bind it before logging so the filter stamps this record with the same
        # id the response carries — see _request_id on why it may be unset here.
        token = request_id_var.set(request_id)
        try:
            logger.exception(
                "Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path
            )
        finally:
            request_id_var.reset(token)
        # The message is generic on purpose; the id is what makes it actionable.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error. Quote the request id when reporting this.",
                "request_id": request_id,
            },
            headers={REQUEST_ID_HEADER: request_id},
        )


def jsonable_errors(exc: RequestValidationError) -> list[dict]:
    """Validation errors with any non-serialisable ``ctx`` value stringified.

    Pydantic puts the original exception object in ``ctx`` for some error types,
    and ``JSONResponse`` cannot encode it — which would turn a 422 into a 500.
    """
    cleaned: list[dict] = []
    for err in exc.errors():
        item = dict(err)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        cleaned.append(item)
    return cleaned
