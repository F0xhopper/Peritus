import logging
import sys

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

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_level: str = "INFO", log_file: str | None = "peritus.log") -> None:
    """Configure root logging for a backend process (API server or worker).

    Logs always go to stderr, which is what `hivemind`/`just dev` captures and
    shows in the terminal. Pass ``log_file`` to additionally tee everything to a
    file. Call once per process, as early as possible.
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    for handler in handlers:
        handler.setFormatter(formatter)

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
