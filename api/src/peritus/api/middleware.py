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
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

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


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id for the duration of the request and log unhandled errors."""

    async def dispatch(self, request: Request, call_next):
        request_id = _clean_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "Unhandled error: %s %s after %.0fms",
                request.method, request.url.path, elapsed_ms,
            )
            raise
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def install_error_handlers(app: FastAPI) -> None:
    """Uniform JSON error bodies, each carrying the request id."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # HTTPException detail is deliberate, author-written text (or, for
        # entitlement denials, a structured payload) — pass it through as-is.
        request_id = current_request_id()
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers={**(exc.headers or {}), REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        request_id = current_request_id()
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_errors(exc), "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request_id = current_request_id()
        logger.exception(
            "Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path
        )
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
