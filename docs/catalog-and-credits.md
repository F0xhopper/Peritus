# Catalog & Credits API

Two things live here: the **public catalog** (finished experts a new user can chat with
immediately, instead of waiting for a build) and the **credit system** that gates builds.

The economic shape: a build costs real money and is paid *before* the user knows whether
they like the product; chat over an already-built expert is cheap. So **builds are gated
and chat is not** — chat over a catalog expert is free and never checks entitlements.

Contracts live in `peritus/api/schemas/experts.py`; behaviour in
`peritus/api/routes/experts.py` and `peritus/billing/`.

---

## Readiness — gate the chat affordance on this, not `status`

Every expert response carries:

```jsonc
{ "readiness": "chat_ready", "graph_expanded": false }
```

| `readiness` | meaning |
|---|---|
| `pending` | not answerable yet |
| `chat_ready` | **answerable** — corpus embedded, concept graph still building |
| `graph_ready` | answerable with graph-expanded retrieval |

An expert becomes answerable at `chat_ready`, a whole stage before `status` becomes
`ready`. **Gate the chat button on `readiness`, not `status`**, or you reintroduce the wait
this was built to remove.

`graph_expanded: false` also means contradictions are **not yet computed** — see
`docs/audit-api.md`.

---

## Catalog

### `GET /experts/catalog` — no auth required

**Query:** `category` · `tag` · `featured` (bool) · `limit` (≤100) · `offset`

Returns `CatalogEntry[]` — a deliberately narrow projection: no `id`, no owner, no `error`,
no build internals. It is the anonymous-readable view.

```jsonc
[
  {
    "name": "…", "topic": "…", "tier": "standard",
    "readiness": "graph_ready", "graph_expanded": true,
    "persona_name": "…", "persona_bio": "…",
    "blurb": "…", "category": "…", "tags": ["…"],
    "is_featured": true,
    "key_concepts": ["…"],
    "source_count": 21, "chunk_count": 412, "node_count": 180,
    "avg_quality": 7.4,
    "source_type_counts": { "pdf": 5, "web": 9, "pubmed": 7 },
    "published_at": "…", "created_at": "…"
  }
]
```

### `GET /experts/catalog/categories` — no auth

`[{ "name": "…", "count": 4 }]`

### `GET /experts/catalog/{slug}` — no auth

One card. Resolves **public and unlisted** slugs: unlisted experts are shareable by link,
they are only absent from the listing. `404` if not found or not chattable.

### Visibility

| value | listed in catalog | reachable by link |
|---|---|---|
| `private` | no | owner only |
| `unlisted` | no | yes |
| `public` | yes | yes |

Listing filters on `readiness <> 'pending'`, so a half-built expert cannot leak onto the
public shelf.

### `PATCH /experts/{slug}/catalog` — owner only

Curation patch. Every field optional; **omitted means "leave alone"**, so removing a value
needs the `clear` list.

```jsonc
{
  "visibility": "public",
  "is_featured": true,
  "catalog_rank": 10,
  "blurb": "…",
  "category": "…",
  "tags": ["…"],
  "clear": ["blurb"]
}
```

Returns `ExpertWithCatalog` — full `ExpertDetail` plus a `catalog` block
(`visibility`, `is_featured`, `catalog_rank`, `blurb`, `category`, `tags`, `published_at`).

Bulk curation is easier from the CLI (`peritus catalog list|publish|unpublish|set|feature|reorder`).

---

## Credits

### `GET /experts/billing/me`

The caller's plan, balance, and the price of each tier. **Provisions the account on first
call**, which is where the free plan's signup grant lands — so call it early.

```jsonc
{
  "plan": {
    "name": "free", "display_name": "Free",
    "included_credits": 1,
    "allowed_tiers": ["lite"],
    "description": "…"
  },
  "balance": 1, "granted": 1, "consumed": 0, "held": 0,
  "credits_enforced": true,
  "tiers": [
    { "tier": "lite", "credit_cost": 1, "spend_cap_usd": 3.0, "included_in_plan": true },
    { "tier": "pro", "credit_cost": 8, "spend_cap_usd": 12.0, "included_in_plan": false }
  ]
}
```

`held` is credits reserved by an in-flight build. `balance` already excludes them —
show `held` separately so a user is not confused by a balance that dropped mid-build.

`credits_enforced: false` means gating is disabled for this deployment; hide credit UI
rather than showing an unlimited balance.

### `GET /experts/billing/ledger`

```jsonc
[
  { "id": 12, "entry_type": "grant", "delta": 5, "job_id": null, "tier": null,
    "reason": "manual grant", "source": "admin", "cost_usd": null, "created_at": "…" },
  { "id": 13, "entry_type": "consume", "delta": -2, "job_id": 41, "tier": "standard",
    "reason": null, "source": "build", "cost_usd": 0.54, "created_at": "…" }
]
```

`cost_usd` is what the build actually spent — the real number from metering, not an
estimate.

### `POST /experts/admin/credits/grant` — admin only

```jsonc
{ "owner": "uuid-or-email", "amount": 5, "reason": "…", "plan": "pro" }
```

Negative `amount` claws back. **No payment provider is integrated** — this is the manual
issuance path, behind a provider-agnostic seam.

---

## Build denial — `402` with a renderable payload

`POST /experts/build` authorizes before enqueueing. On refusal the `detail` is a structured
object, not prose. **Switch on `code`; do not parse the message.**

```jsonc
{
  "detail": {
    "code": "insufficient_credits",
    "message": "This standard build costs 2 credits, and you have 1.",
    "required_credits": 2,
    "available_credits": 1,
    "tier": "standard",
    "plan": "free",
    "remedy": { "kind": "request_credits", "label": "Request credits", "detail": "…" }
  }
}
```

| `code` | meaning | `remedy.kind` |
|---|---|---|
| `insufficient_credits` | not enough credits for this tier | `request_credits` |
| `tier_not_in_plan` | tier unavailable on this plan (carries `allowed_tiers`) | `change_tier` |

`remedy` is a **UI hint, not a route** — there is no checkout, so today the remedy is "ask".
Render it as the single available action; the shape will not change when checkout exists.

### `GET /experts/{slug}/build/usage`

Per-build spend, attributed by stage (triage, validation, contextualization, graph
extraction, persona, embeddings). Useful for "what did this build cost me".

### Spend caps

Each tier carries a per-build USD ceiling. If a running build crosses it, the worker fails
the job **terminally** — a retry would spend the same money again — and **the credit hold is
refunded**. Surface this as a cap event, not a generic build failure: the user did not lose
credits, and retrying unchanged will not help.

---

## Free tier, in one line

Free = **chat over the catalog, unlimited**. Builds cost credits. That is the whole model,
and it exists because a build's cost is incurred before a user can judge the product.
