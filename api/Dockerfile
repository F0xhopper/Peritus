# syntax=docker/dockerfile:1.7
#
# One image, two process types (see fly.toml [processes]):
#   API:    peritus-server
#   Worker: peritus-worker
# so an API restart/deploy never kills an in-flight build, and workers scale
# independently. For a single-process local setup, run only the API with
# RUN_WORKER_IN_PROCESS=true.

# ── Build: resolve the locked dependency set into a self-contained venv ───────
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

# The venv lives outside /app so the runtime stage can copy it whole; bytecode
# is compiled here so the first request of a fresh machine does not pay for it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile alone: this layer is reused by every
# build that changes only application code. `--frozen` fails the build rather
# than silently re-resolving — the image installs exactly what CI tested, not
# whatever PyPI's newest major release is on the day of the deploy.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ── Runtime: no compiler, no uv, no source tree — just the venv ───────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# /app is the working directory and must be writable: the `peritus` CLI (e.g.
# from `fly ssh console`) writes peritus.log into it.
RUN useradd --create-home --uid 10001 peritus \
    && install -d -o peritus -g peritus /app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# The release_command runs `python migrations/apply.py` from /app.
COPY migrations/ migrations/

USER peritus

EXPOSE 8000

CMD ["peritus-server"]
