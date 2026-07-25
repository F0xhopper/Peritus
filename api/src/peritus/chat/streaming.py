"""Shared chat-stream body: retrieval → composition → token stream → citations.

Both chat endpoints consume this one generator so they cannot drift:

- the stateless ``POST /experts/{slug}/chat`` (TUI/CLI contract) wraps it in a
  try/except that emits an ``error`` event, exactly as before;
- the stateful ``POST /conversations/{id}/messages`` additionally accumulates
  the answer for persistence and prepends a ``meta`` event.

Yields plain event dicts (``status`` / ``token`` / ``sources`` / ``done``) and
**raises** on failure rather than yielding ``error`` — persistence of partial
answers is the caller's concern, and it needs the exception.

Prompt-cache economics are unchanged: ``build_cached_system`` keeps the
byte-identical system prompt breakpoint, ``build_composition_messages`` keeps
the trailing-history breakpoint, so follow-up turns bill prior context at
~0.1× regardless of whether history came from the request body or Postgres.
"""

from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from peritus.chat.agent import (
    ChatAgent,
    RetrievedContext,
    build_cached_system,
    build_composition_messages,
)
from peritus.chat.grounding import parse_cited_indices, used_citations
from peritus.core.config import settings
from peritus.experts.domain import Expert
from peritus.infrastructure.anthropic_client import get_anthropic_client


async def stream_expert_answer(
    pool: asyncpg.Pool,
    expert: Expert,
    question: str,
    history: list[dict],
) -> AsyncIterator[dict[str, Any]]:
    # Retrieval pipeline (shared with ChatAgent.respond), statuses streamed.
    agent = ChatAgent(pool)
    ctx: RetrievedContext | None = None
    async for kind, payload in agent.retrieve(expert, question):
        if kind == "status":
            yield {"type": "status", "message": payload}
        elif isinstance(payload, RetrievedContext):
            ctx = payload
    assert ctx is not None

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

    yield {"type": "done"}
