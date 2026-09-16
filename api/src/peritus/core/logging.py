import contextlib
import contextvars
import logging
import sys
from collections.abc import Iterator

# Third-party libraries that log a line per HTTP request / low-level frame at
# INFO or DEBUG. Left unfiltered they drown out our own logs, so pin them a step
# quieter than the app. Bump any of these to the root level for deep debugging.
_NOISY_LOGGERS = (
    "httpcore",
    "urllib3",
    "hpack",
    "asyncio",
    "multipart",
    "python_multipart",
)

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The correlation slot for whatever is currently being handled: one field, two
# fillers. The API's RequestContextMiddleware puts the request id in it; the
# worker puts the job it is running (see :func:`job_context`). Lives here, in
# the logging module, because that is what makes the layering work: everything
# logs, and nothing below the API layer should have to import from it. Anything
# outside both — a CLI build, a startup banner — reads "-".
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "peritus_request_id", default="-"
)


def current_request_id() -> str:
    return request_id_var.get()


@contextlib.contextmanager
def job_context(job_id: int, expert_id: int | None = None) -> Iterator[None]:
    """Stamp every log line inside this block with the job it belongs to.

    A build is minutes of interleaved output from a dozen modules across
    `WORKER_CONCURRENCY` concurrent jobs, and until this every one of those lines
    carried `-`. Which build a line came from had to be inferred from its text.
    Now `grep 'job=53'` is the whole answer.

    Context variables follow the task, so a line logged inside a `gather` under
    this block is stamped too.
    """
    label = f"job={job_id}" + (f" expert={expert_id}" if expert_id is not None else "")
    token = request_id_var.set(label)
    try:
        yield
    finally:
        request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """Stamp the current correlation label on every record.

    A filter rather than a LoggerAdapter so third-party records (uvicorn,
    anthropic, asyncpg) get the field too — without it, the format string above
    would raise on the first log line any library emits.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(log_level: str = "INFO", log_file: str | None = None) -> None:
    """Configure root logging for a backend process (API server or worker).

    Logs always go to stderr, which is what `hivemind`/`just dev` captures and
    shows in the terminal. Pass ``log_file`` to additionally tee everything to a
    file. Call once per process, as early as possible.

    ``log_file`` defaults to None rather than ``"peritus.log"``: the old default
    wrote a log into whatever directory the CLI happened to be run from, which
    is how ``api/peritus.log`` came to sit in the source tree. Callers that want
    a file say so — the servers pass ``settings.LOG_FILE``.
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    request_id_filter = RequestIdFilter()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    for handler in handlers:
        handler.setFormatter(formatter)
        # On the handler, not the logger: filters on a logger do not apply to
        # records that propagate up from its children, and most records here
        # come from child loggers.
        handler.addFilter(request_id_filter)

    logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        force=True,
    )

    # Uvicorn runs with log_config=None (see api/app.py), so its loggers propagate
    # to the root config above. Keep request access logs at INFO regardless of
    # verbosity elsewhere, and quiet the chatty transport libraries.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))

    # Surface warnings.warn(...) through logging instead of stderr prints so they
    # get the same format, level, and file handler as everything else.
    logging.captureWarnings(True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
