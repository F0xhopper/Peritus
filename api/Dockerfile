FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY migrations/ migrations/

RUN pip install --no-cache-dir .

RUN useradd -m peritus && chown -R peritus /app
USER peritus

EXPOSE 8000

# Run the same image as two process types (recommended for production):
#   API:    peritus-server
#   Worker: peritus-worker
# so an API restart/deploy never kills an in-flight build, and workers scale
# independently. For a single-process local setup, run only the API with
# RUN_WORKER_IN_PROCESS=true.
CMD ["peritus-server"]
