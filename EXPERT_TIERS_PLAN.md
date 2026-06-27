# Expert Tiers Implementation Plan

## Problem

Every expert is built and queried with identical hardcoded parameters scattered across the codebase. There is no way to create a lightweight "10-source" expert vs a deep "100-source" expert, and query depth is equally fixed. This plan replaces those magic numbers with a structured tier system.

---

## Design

### The Two Phases

Expert scale is controlled at two separate moments:

| Phase | When | What it controls |
|---|---|---|
| **Build-time** | `ExpertBuilder.build()` | How many sources are fetched and ingested |
| **Query-time** | `ChatAgent.respond()` / `chat.py` route | How deeply retrieved, graph hops, response length |

Both are driven by a single `ExpertConfig` stored per expert, derived from its `ExpertTier`.

---

### `ExpertTier` + `ExpertConfig`

```python
class ExpertTier(str, Enum):
    LITE     = "lite"      # fast, cheap — ~10 sources ingested
    STANDARD = "standard"  # current behaviour — ~20 sources ingested
    PRO      = "pro"       # deep — ~40 sources ingested

@dataclass(frozen=True)
class ExpertConfig:
    source_multiplier: float   # scales per-fetcher max_results at build time
    retrieval_top_k: int       # chunks per subquery in hybrid search
    max_subqueries: int        # planning breadth (subquery count cap)
    graph_hops: int            # expansion depth in GraphRetriever.expand()
    coverage_extra_k: int      # fallback retrieval top_k on unsatisfied coverage
    max_context_passages: int  # passages passed into the LLM context block
    max_response_tokens: int   # Claude max_tokens for the final answer

    @classmethod
    def from_tier(cls, tier: ExpertTier) -> "ExpertConfig":
        return _TIER_DEFAULTS[tier]
```

**Tier defaults:**

| Field | LITE | STANDARD | PRO |
|---|---|---|---|
| `source_multiplier` | 0.5 | 1.0 | 2.0 |
| Expected sources (post-validation) | ~10 | ~20 | ~40 |
| `retrieval_top_k` | 5 | 10 | 20 |
| `max_subqueries` | 2 | 4 | 6 |
| `graph_hops` | 1 | 1 | 2 |
| `coverage_extra_k` | 3 | 5 | 10 |
| `max_context_passages` | 8 | 15 | 25 |
| `max_response_tokens` | 1024 | 2048 | 4096 |

**Rationale for each field:**
- `source_multiplier` — scales the per-fetcher `max_results` in `_build_fetchers()`. At 0.5×: wiki=1, exa=2, etc. At 2×: wiki=6, exa=10, etc. The existing `depth="deep"` was already doing 2× — PRO formalises this.
- `retrieval_top_k` — top chunks per subquery. Directly controls how much of the knowledge base each query sees.
- `max_subqueries` — caps the planning tool's `maxItems`. PRO allows broader decomposition of complex questions.
- `graph_hops` — `GraphRetriever.expand()` already accepts this param (hardcoded call site passes nothing, defaulting to 1). PRO adds a second hop for richer concept linking.
- `coverage_extra_k` — fallback retrieval when coverage is unsatisfied. Higher tier = more aggressive gap-filling.
- `max_context_passages` — cap on `enriched[:N]` fed to the LLM. More passages = richer grounding, higher cost.
- `max_response_tokens` — Claude `max_tokens`. LITE gets concise answers; PRO gets comprehensive ones.

---

## What Changes

### 1. `peritus/experts/domain.py`

Add `ExpertTier`, `ExpertConfig`, and `_TIER_DEFAULTS` dict. Add `tier: ExpertTier` and `config: ExpertConfig` fields to the `Expert` dataclass. `config` is derived from `tier` but stored separately so future code can override individual fields without changing tier.

### 2. DB Migration

```sql
ALTER TABLE experts
    ADD COLUMN tier    VARCHAR(16) NOT NULL DEFAULT 'standard',
    ADD COLUMN config  JSONB       NOT NULL DEFAULT '{}';
```

Existing rows get `tier='standard'` and `config='{}'` automatically. The repository reads the stored `config` JSONB and, if it is empty, falls back to `ExpertConfig.from_tier(tier)`. This makes the migration zero-downtime.

### 3. `peritus/experts/repository.py`

- `create(name, topic, tier)` — accepts tier, computes config, inserts both columns.
- `_row_to_expert()` — deserialises `tier` and `config`; if config is `{}`, derives it from tier.
- Add `update_config(expert_id, config)` for future admin overrides.

### 4. `peritus/experts/builder.py`

Replace `depth: str` constructor param with reading `expert.config.source_multiplier`. The `_build_fetchers()` multiplier becomes `expert.config.source_multiplier`. Remove `self._depth` entirely.

**Current (hardcoded):**
```python
multiplier = 2 if depth == "deep" else 1
self._fetchers = self._build_fetchers(multiplier, source_filter)
```

**After:**
```python
self._fetchers = self._build_fetchers(expert.config.source_multiplier, source_filter)
```

Note: `build()` receives the `Expert` object already, so `expert.config` is always available.

### 5. `peritus/chat/agent.py`

Replace all hardcoded pipeline values with `expert.config.*`. The `respond()` signature already takes `expert: Expert`.

**Hardcoded values to replace:**

| Location | Current | Replacement |
|---|---|---|
| `batch_search(top_k=10)` | `10` | `expert.config.retrieval_top_k` |
| `_graph.expand(..., hops=...)` | missing (defaults to 1) | `expert.config.graph_hops` |
| `coverage["suggested_queries"][:3]` | `3` | `expert.config.max_subqueries // 2` |
| `batch_search(top_k=5)` (coverage fallback) | `5` | `expert.config.coverage_extra_k` |
| `passages[:15]` in `_assess_coverage` | `15` | `expert.config.max_context_passages` |
| `enriched[:15]` in `_build_context` | `15` | `expert.config.max_context_passages` |
| `max_tokens=2048` | `2048` | `expert.config.max_response_tokens` |

The `_PLAN_TOOL` schema has `maxItems: 4` hardcoded for subqueries — update to `expert.config.max_subqueries` by passing it as a parameter to `_plan()`.

### 6. `peritus/api/routes/chat.py`

This route duplicates the entire pipeline from `agent.py` with the same hardcoded values. Replace all hardcoded numbers with `expert.config.*` in exactly the same way as step 5. (Longer term, this route should delegate to `agent.respond()` to remove the duplication entirely — out of scope for this plan.)

### 7. API Schema + Route

**`peritus/api/schemas/experts.py`:**
```python
from peritus.experts.domain import ExpertTier

class BuildRequest(BaseModel):
    topic: str
    tier: ExpertTier = ExpertTier.STANDARD
    # remove: depth: str = "normal"

class ExpertSummary(BaseModel):
    ...
    tier: str  # add this field
```

**`peritus/api/routes/experts.py`:**  
Update `build_expert()` to pass `req.tier` to `repo.create()` and `ExpertBuilder`.

---

## Quality Assurance

### Unit Tests

**`tests/unit/test_expert_config.py`**

1. **Tier defaults are correct** — `ExpertConfig.from_tier(LITE)`, `.from_tier(STANDARD)`, `.from_tier(PRO)` each produce exactly the expected field values.

2. **Monotonicity property** — for every numeric field in `ExpertConfig`, `LITE ≤ STANDARD ≤ PRO`. This is a table-driven test that will catch any future accidental regression.

3. **Serialisation roundtrip** — `config → json.dumps(dataclasses.asdict(config)) → ExpertConfig(**json.loads(...))` produces an equal object. Validates the JSONB storage contract.

4. **Empty config fallback** — `_row_to_expert` given `config={}` and `tier='standard'` returns an expert whose config equals `ExpertConfig.from_tier(STANDARD)`. Validates the migration safety net.

5. **Unknown tier rejection** — `ExpertTier("ultra")` raises `ValueError`. Validates API input validation.

### Integration Tests

**`tests/integration/test_builder_tiers.py`**

6. **LITE builder uses correct multiplier** — mock `_build_fetchers`, assert it is called with `source_multiplier=0.5`. Does not require network or DB.

7. **PRO builder uses correct multiplier** — same as above with `2.0`.

8. **Chat pipeline top_k propagates** — create a fake `Expert` with LITE config, mock `SearchService.batch_search`, call `ChatAgent.respond()`, assert `batch_search` was called with `top_k=5`.

9. **PRO chat pipeline top_k** — same with PRO config, expect `top_k=20`.

10. **Graph hops propagates** — mock `GraphRetriever.expand`, assert it is called with `hops=1` for STANDARD and `hops=2` for PRO.

### API Contract Tests

**`tests/api/test_build_endpoint.py`**

11. **Valid tier accepted** — `POST /experts/build {"topic": "stoicism", "tier": "lite"}` returns 200.

12. **Invalid tier rejected** — `POST /experts/build {"topic": "stoicism", "tier": "ultra"}` returns 422.

13. **Default tier is standard** — `POST /experts/build {"topic": "stoicism"}` (no tier) creates an expert with `tier="standard"`.

14. **Tier surfaced in GET response** — after build, `GET /experts/stoicism` returns `"tier": "lite"` in the response body.

---

## Implementation Order

1. `domain.py` — add `ExpertTier`, `ExpertConfig`, `_TIER_DEFAULTS`, update `Expert` dataclass
2. Unit tests 1–5 (write them first, run them red)
3. DB migration
4. `repository.py` — read/write tier + config
5. Unit test 4 goes green
6. `builder.py` — replace `depth` with `expert.config.source_multiplier`
7. Integration tests 6–7 go green
8. `agent.py` — replace all hardcoded values
9. Integration tests 8–10 go green
10. `chat.py` route — replace all hardcoded values (mirrors agent.py changes)
11. `schemas/experts.py` + `routes/experts.py` — API surface
12. API contract tests 11–14 go green

---

## Files Touched

| File | Change |
|---|---|
| `api/src/peritus/experts/domain.py` | Add `ExpertTier`, `ExpertConfig`, `_TIER_DEFAULTS`; extend `Expert` |
| `api/src/peritus/experts/repository.py` | Read/write `tier` + `config` columns; add `update_config()` |
| `api/src/peritus/experts/builder.py` | Replace `depth` string with `expert.config.source_multiplier` |
| `api/src/peritus/chat/agent.py` | Replace 7 hardcoded constants with `expert.config.*` |
| `api/src/peritus/api/routes/chat.py` | Same as agent.py |
| `api/src/peritus/api/schemas/experts.py` | `BuildRequest.tier`, `ExpertSummary.tier` |
| `api/src/peritus/api/routes/experts.py` | Pass `req.tier` through to repo + builder |
| `api/migrations/XXXX_expert_tiers.sql` | Add `tier` + `config` columns with safe defaults |
| `tests/unit/test_expert_config.py` | 5 unit tests |
| `tests/integration/test_builder_tiers.py` | 5 integration/mock tests |
| `tests/api/test_build_endpoint.py` | 4 contract tests |

No other files need to change. The `GraphRetriever.expand()` signature already accepts `hops` — it just was never called with it explicitly.
