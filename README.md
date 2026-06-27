# Peritus

Build grounded AI subject-matter experts from multi-source corpora.

Give Peritus a topic. It discovers authoritative sources across the web, has Claude validate and score each one, ingests and embeds the survivors, extracts a concept graph over the content, and generates a named expert persona you can converse with — every answer cited back to the passages it came from.

Peritus is two components:

- **`api/`** — a Python 3.12 / FastAPI server that runs the build pipeline and the retrieval-augmented chat, streaming progress and tokens over Server-Sent Events.
- **`cli/`** — a Rust [ratatui](https://ratatui.rs) terminal UI that talks to the server: browse experts, kick off builds with a live log, and chat.

Storage is PostgreSQL + [pgvector](https://github.com/pgvector/pgvector). There is no external vector database — the corpus, the concept graph, and the chunk embeddings all live in Postgres.

## How it works

### Build

```
build "stoic philosophy"   (tier: lite · standard · pro)
```

1. **Plan** — Claude turns the topic into a tailored search query for each source fetcher and names the 5–8 core concepts the corpus must cover.
2. **Discover** — every fetcher runs concurrently: Wikipedia, Project Gutenberg, ArXiv, PDFs (Mistral OCR), YouTube transcripts, Exa neural search, general web, Reddit, and curated thought-leaders. High-citation references from discovered ArXiv papers are snowballed in via Semantic Scholar.
3. **Validate** — Claude scores each source for quality and relevance against a versioned rubric; sources below threshold are dropped, with the reason recorded.
4. **Chunk & embed** — survivors are chunked, given Anthropic-style contextual prefixes, and embedded with OpenAI `text-embedding-3-large` (3072-dim).
5. **Graph extract** — Claude reads the chunks in batches and extracts typed concept nodes and relationships (including `contradicts` edges). Semantically duplicate nodes are then merged via embedding similarity.
6. **Persona** — Claude reads a digest of the accepted sources and the top concepts and writes a named expert persona: name, bio, and a concrete speaking/citation style.

Every passed and dropped source — with its quality/relevance scores, validator model, and rubric version — is persisted, so each expert carries a verifiable record of what it was built from.

### Chat

Each question is answered through a grounded retrieval loop:

1. **Plan** subqueries from the question.
2. **Hybrid search** every subquery in parallel — semantic (pgvector) fused with keyword (Postgres full-text) via reciprocal-rank fusion, then optionally reranked (Cohere cross-encoder, or a windowed LLM fallback).
3. **Graph expand** the hits with neighbouring concepts and relationships from the concept graph.
4. **Coverage check** — Claude judges whether the retrieved passages answer the question and, if not, suggests follow-up queries for a second retrieval pass.
5. **Compose** — the deduplicated passages are numbered and handed to Claude under a strict grounding contract: answer only from the passages, cite every claim with its `[n]`.
6. **Stream** the answer token-by-token, then resolve the citation list down to only the passages the answer actually cited.

## Tiers

A tier sets the depth/cost trade-off for both build and chat (`api/.../experts/domain.py`):

| Tier     | Sources | Subqueries | Graph hops | Context passages | Response tokens |
|----------|---------|-----------|-----------|------------------|-----------------|
| lite     | ~10     | 2         | 1         | 8                | 1024            |
| standard | ~20     | 4         | 1         | 15               | 2048            |
| pro      | ~40     | 6         | 2         | 25               | 4096            |

## Requirements

- Python 3.12+
- Rust (stable) — only to build the TUI client
- PostgreSQL with the `pgvector` extension
- `ANTHROPIC_API_KEY` — validation, graph extraction, persona, chat
- `OPENAI_API_KEY` — embeddings
- Optional: `EXA_API_KEY` (Exa neural search + YouTube discovery), `MISTRAL_API_KEY` (PDF OCR), `COHERE_API_KEY` (cross-encoder reranking)

## Setup

```bash
# 1. Configure
cp .env.example .env        # then fill in DATABASE_URL + API keys

# 2. Install the API and apply migrations
cd api
pip install -e .
python migrations/apply.py

# 3. Build the Rust TUI client
cd ../cli
cargo build --release
```

Key environment variables (`api/src/peritus/core/config.py`):

| Variable               | Purpose                                            | Default                      |
|------------------------|----------------------------------------------------|------------------------------|
| `DATABASE_URL`         | Postgres connection string                         | —                            |
| `ANTHROPIC_API_KEY`    | Claude (validation, graph, persona, chat)          | —                            |
| `OPENAI_API_KEY`       | Embeddings                                         | —                            |
| `CLAUDE_MODEL`         | Chat + persona model                               | `claude-sonnet-4-6`          |
| `FAST_MODEL`           | Planning, contextualisation, coverage, validation  | `claude-haiku-4-5-20251001`  |
| `GRAPH_MODEL`          | Graph extraction                                   | `claude-haiku-4-5-20251001`  |
| `EMBED_MODEL` / `EMBED_DIM` | OpenAI embedding model / dimension            | `text-embedding-3-large` / `3072` |
| `EXA_API_KEY`          | Exa + YouTube discovery (optional)                 | —                            |
| `MISTRAL_API_KEY`      | PDF OCR (optional)                                 | —                            |
| `COHERE_API_KEY`       | Cross-encoder reranking (optional)                 | —                            |
| `PERITUS_API_KEY_HASH` | SHA-256 of the API key required by clients; unset = open dev mode | —             |

## Running

The repo ships a `Justfile` with the common commands:

```bash
just dev          # run the API server (uvicorn, :8000, --reload)
just migrate      # apply database migrations
just test         # pytest
just lint         # ruff + mypy
just build-cli    # cargo build --release
just run-cli      # cargo run  (the TUI)
just docker-up    # docker compose up --build -d
just docker-down
```

Typical flow: start the server (`just dev`), then launch the TUI (`just run-cli`). On first run the TUI shows a config screen — point it at the server URL (default `http://localhost:8000`) and paste the API key if the server has `PERITUS_API_KEY_HASH` set. From the home screen you can create an expert (topic + tier) and watch the build log live, then open it to chat.

Generate an API key and its hash with:

```bash
python -c "from peritus.api.app import keygen; keygen()"
```

## API

All endpoints require the key via `X-API-Key:` or `Authorization: Bearer` when `PERITUS_API_KEY_HASH` is set.

| Method   | Path                      | Description                                  |
|----------|---------------------------|----------------------------------------------|
| `GET`    | `/health`, `/ready`       | Liveness / DB readiness                       |
| `GET`    | `/experts`                | List experts                                  |
| `GET`    | `/experts/{slug}`         | Expert detail (sources, counts, persona)      |
| `POST`   | `/experts/build`          | Build an expert — **SSE** stream of progress  |
| `DELETE` | `/experts/{slug}`         | Delete an expert                              |
| `POST`   | `/experts/{slug}/chat`    | Ask a question — **SSE** stream of tokens + citations |

## Project layout

```
api/
  src/peritus/
    api/          FastAPI app, routes, schemas, auth
    experts/      build pipeline coordinator, tiers, repository
    sources/      fetchers (wikipedia, arxiv, exa, web, …) + Claude validator
    ingestion/    chunking, contextualisation, embed pipeline
    graph/        concept-graph extraction, storage, retrieval
    search/       hybrid semantic + keyword search service
    chat/         grounded chat agent, grounding contract, faithfulness
    eval/         offline golden-set harness + retrieval/answer metrics
    infrastructure/  Postgres pool, embeddings, reranker, Anthropic client, PDF OCR
  migrations/     SQL migrations + apply.py
cli/
  src/
    api/          HTTP + SSE client
    tui/          ratatui screens (home, build, chat, config) and widgets
    config/       on-disk client config (server URL + key)
```
