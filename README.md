# Peritus

**Domain-expert-first AI learning system with graph-grounded knowledge.**

*Peritus* (Latin: "expert") builds a reusable, graph-grounded AI tutor for any topic. Give it a domain — it researches authoritative sources, constructs a PropertyGraphIndex, and creates a persistent expert persona. You can then generate structured courses or hold open-ended tutoring conversations, all grounded in the expert's knowledge graph.

---

## Philosophy

The UI is intentionally minimal — monospace font, plain text layout, textbook-like feel. No cards, no gradients, no animations. Just content.

---

## Architecture

```
peritus/
├── backend/               Python 3.12 + FastAPI
│   ├── domain/            Pure entities (Expert, Course, ChatMessage)
│   ├── application/       Use cases (create_expert, generate_course, converse)
│   ├── infrastructure/    LLM, embeddings, Pinecone, graph, sources
│   ├── interfaces/        FastAPI routers (experts, courses, chat)
│   └── core/              Config, exceptions, logging
└── frontend/              Next.js 15 App Router + TypeScript
    ├── app/               Pages (home, experts, chat, course)
    └── lib/               API fetch helpers
```

**Tech stack:**
- LLM: Claude 3.5 Sonnet (Anthropic)
- Embeddings: Voyage-3 (1024-dim)
- Graph index: LlamaIndex PropertyGraphIndex
- Vector store: Pinecone (namespace per expert)
- Graph persist: local disk (`./storage/peritus/{slug}`)
- Sources: Exa (neural search), ArXiv, Firecrawl, YouTube Transcripts, Unstructured.io

---

## Setup

### 1. Clone & configure

```bash
git clone <repo>
cd peritus
cp .env.example .env
# Fill in your API keys in .env
```

Required keys:
- `ANTHROPIC_API_KEY`
- `VOYAGE_API_KEY`
- `PINECONE_API_KEY`
- `EXA_API_KEY`

Optional:
- `FIRECRAWL_API_KEY` — richer content extraction (falls back gracefully if missing)

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env       # or create .env in project root
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

Swagger UI: `http://localhost:8000/docs`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at `http://localhost:3000`.

---

## Usage

### Build an expert

1. Open `http://localhost:3000`
2. Enter a topic (e.g. "Byzantine Fault Tolerance", "Bayesian Statistics")
3. Click **Build Expert →**
4. Watch the progress stream as Peritus:
   - Discovers sources (Exa neural search)
   - Enriches content (Firecrawl)
   - Fetches ArXiv papers
   - Builds the PropertyGraphIndex
   - Generates the expert persona

### Generate a course

1. Navigate to your expert's page
2. Click **Generate a course →**
3. Choose difficulty: `beginner` / `intermediate` / `advanced` / `custom`
4. The course streams as live Markdown with modules, concepts, and examples

### Chat with your expert

1. Navigate to your expert's page
2. Click **Start a conversation →**
3. Every response is grounded in the expert's knowledge graph
4. The conversation is stateful — ask follow-up questions naturally

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/experts/create` | Build expert (SSE stream) |
| `GET`  | `/api/experts` | List all experts |
| `GET`  | `/api/experts/{slug}` | Get expert details |
| `POST` | `/api/courses/generate` | Generate course (stream) |
| `POST` | `/api/chat/{slug}` | Chat message (SSE stream) |
| `GET`  | `/api/chat/{slug}/history` | Conversation history |
| `DELETE` | `/api/chat/{slug}/history` | Clear conversation |
| `GET`  | `/health` | Health check |

---

## UI Philosophy

The Peritus frontend is inspired by reading plain Markdown in a text editor or a printed computer science textbook:

- **Font:** JetBrains Mono / Inconsolata / Fira Mono (monospace stack)
- **Layout:** Single column, max-width 82ch, generous line-height (1.8)
- **Colour:** Near-black text (#111) on very light cream (#fdfdf6)
- **No:** gradients, shadows, rounded corners > 2px, animations, cards
- **Chat format:** `> user message` / `Expert Name: response`
- **Markdown:** react-markdown with plain CSS overrides

---

## Environment Variables

See `.env.example` for all options. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `VOYAGE_API_KEY` | Yes | VoyageAI embeddings |
| `PINECONE_API_KEY` | Yes | Pinecone vector store |
| `EXA_API_KEY` | Yes | Exa neural search |
| `FIRECRAWL_API_KEY` | No | Deep web crawling |
| `MAX_SOURCE_DOCS` | No | Sources per expert (default: 20) |
| `MAX_PATHS_PER_CHUNK` | No | Graph paths per chunk (default: 15) |
