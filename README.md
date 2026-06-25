# Peritus

Build grounded AI subject-matter experts from multi-source corpora.

Run one command with a topic. Peritus fetches sources automatically (Wikipedia, ArXiv, YouTube, Exa, web), has Claude validate and score each one, builds a property graph over the validated content, and generates a named expert persona ready to answer questions with full citations.

## How it works

```
peritus build "stoic philosophy"
```

1. **Discover** — pulls sources from Wikipedia, ArXiv, YouTube, Exa, and the web concurrently
2. **Validate** — Claude scores each source for quality and relevance; low-scoring sources are dropped and logged
3. **Chunk & embed** — content is semantically chunked, contextualised, and embedded via `text-embedding-3-large`
4. **Graph extract** — Claude reads chunks in batches and extracts typed concept nodes and relationships
5. **Persona generate** — Claude reads the source digest and top concepts, then generates a named expert persona

```
peritus chat "stoic philosophy"
```

Questions are decomposed into subqueries, run through hybrid vector + full-text search, expanded via the concept graph, and answered in persona with inline citations you can trace back to the original sources.

## Requirements

- Python 3.11+
- PostgreSQL with pgvector
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` (embeddings)
- `EXA_API_KEY` (optional — enables Exa neural search and YouTube discovery)

## Setup

```bash
pip install -e .
cp .env.example .env
# fill in your API keys in .env

# apply database migrations
python migrations/apply.py
```

## Usage

```bash
# Build an expert (fully automatic)
peritus build "stoic philosophy"
peritus build "quantum computing" --depth deep
peritus build "machine learning" --sources arxiv,exa

# Chat with an expert
peritus chat "stoic philosophy"

# View an expert's credential card (sources, scores, dropped sources, top concepts)
peritus credentials "stoic philosophy"

# Manage experts
peritus experts list
peritus experts show "stoic philosophy"
peritus experts delete "stoic philosophy"
peritus rebuild "stoic philosophy"

# Config
peritus config show
peritus config set ANTHROPIC_API_KEY=sk-...
```

## Credential card

Every expert carries a verifiable record of every source Claude accepted or rejected, quality and relevance scores, and the top concepts extracted from the corpus. This is shown on `peritus credentials` and as a header when entering chat.
