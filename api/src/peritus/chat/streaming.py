"""Shared chat-stream body: retrieval → composition → token stream → citations.

Both chat endpoints consume this one generator so they cannot drift:

- the stateless ``POST /experts/{slug}/chat`` (TUI/CLI contract) wraps it in a
  try/except that emits an ``error`` event, exactly as before;
- the stateful ``POST /conversations/{id}/messages`` additionally accumulates
  the answer for persistence and prepends a ``meta`` event.

Yields plain event dicts (``status`` / ``token`` / ``sources`` /
``retrieval_audit`` / ``done``) and **raises** on failure rather than yielding
``error`` — persistence of partial answers is the caller's concern, and it needs
the exception.

``retrieval_audit`` carries the answer's provenance: how many passages were
retrieved, how many reached the prompt, how many the answer cited, and what
happened to each one. It is a trail, never a score — see ``chat/audit_trail.py``.
Both routes forward unrecognised event types verbatim, so it reaches every
client without either route changing.

Prompt-cache economics are unchanged: ``build_cached_system`` keeps the
byte-identical system prompt breakpoint, ``build_composition_messages`` keeps
the trailing-history breakpoint, so follow-up turns bill prior context at
~0.1× regardless of whether history came from the request body or Postgres.
"""

from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from peritus.audit.service import AuditService
from peritus.chat.agent import (
    ChatAgent,
    RetrievedContext,
    build_cached_system,
    build_composition_messages,
)
from peritus.chat.audit_trail import audit_db_rows, build_audit_payload
from peritus.chat.grounding import parse_cited_indices, used_citations
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.search.readiness import get_readiness

logger = get_logger(__name__)


async def stream_expert_answer(
    pool: asyncpg.Pool,
    expert: Expert,
    question: str,
    history: list[dict],
    conversation_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    # Retrieval pipeline (shared with ChatAgent.respond), statuses streamed.
    agent = ChatAgent(pool)
    ctx: RetrievedContext | None = None
    async for kind, payload in agent.retrieve(expert, question):
        if kind == "status":
            yield {"type": "status", "message": payload}
        elif isinstance(payload, RetrievedContext):
            ctx = payload
    if ctx is None:
        # Not an assertion: `python -O` strips those, and the next line would
        # then fail with an AttributeError that says nothing about the cause.
        raise RuntimeError("Retrieval pipeline ended without producing a context")

    # Stream the Anthropic response token by token. System prompt and history
    # carry prompt-cache breakpoints so follow-up turns read the shared prefix
    # at ~0.1× input price.
    messages = build_composition_messages(history, question, ctx.context_block)
    client = get_anthropic_client()
    answer_parts: list[str] = []
    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=expert.config.max_response_tokens,
        system=build_cached_system(expert.persona_style, expert.topic),
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            answer_parts.append(text)
            yield {"type": "token", "text": text}

    # Resolve citations: only passages the answer actually cited, with the
    # passage numbers preserved so inline [n] matches the rendered list.
    answer_text = "".join(answer_parts)
    cited = parse_cited_indices(answer_text, len(ctx.passages))
    sources = used_citations(ctx.passages, cited)
    yield {
        "type": "sources",
        "citations": sources,
        "has_contradiction": ctx.has_contradiction,
    }

    # Audit trail for this answer: what was retrieved, what reached the prompt,
    # what the answer cited. Emitted after the citations and before `done`, so a
    # client that only handles the older events is unaffected. Best-effort in
    # full: the answer has already been delivered, and no failure in accounting
    # for it may turn it into an error.
    try:
        graph_ready = (await get_readiness(pool, expert.id)).graph_expanded
        payload = build_audit_payload(
            trail=ctx.trail,
            passages=ctx.passages,
            cited=cited,
            answer_text=answer_text,
            has_contradiction=ctx.has_contradiction,
            graph_ready=graph_ready,
        )
        header, rows = audit_db_rows(payload, expert.id, conversation_id, question)
        audit_id = await AuditService(pool).record_answer_audit(header, rows)
        yield {
            "type": "retrieval_audit",
            "audit_id": audit_id,
            "persisted": audit_id is not None,
            **payload,
        }
    except Exception:
        logger.warning("Retrieval audit unavailable for expert %d", expert.id, exc_info=True)

    yield {"type": "done"}
