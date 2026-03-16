from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core.exceptions import ConversationError, ExpertNotFoundError
from core.logger import get_logger
from domain.entities import Conversation, Expert, ExpertStatus
from infrastructure.graph.llama_graph_repo import load_graph_index
from infrastructure.llm.anthropic_adapter import (
    build_expert_system_prompt,
    stream_completion,
)

logger = get_logger(__name__)

_CONVERSATIONS: dict[str, Conversation] = {}

_MAX_HISTORY_MESSAGES = 20


def get_or_create_conversation(expert_slug: str) -> Conversation:
    if expert_slug not in _CONVERSATIONS:
        _CONVERSATIONS[expert_slug] = Conversation(expert_slug=expert_slug)
    return _CONVERSATIONS[expert_slug]


def reset_conversation(expert_slug: str) -> None:
    _CONVERSATIONS.pop(expert_slug, None)


async def _retrieve_graph_context(expert: Expert, user_message: str) -> str:
    try:
        index = await asyncio.get_event_loop().run_in_executor(
            None, load_graph_index, expert.slug
        )
        query_engine = index.as_query_engine(
            include_text=True,
            similarity_top_k=5,
        )
        response = await asyncio.get_event_loop().run_in_executor(
            None, query_engine.query, user_message
        )
        context = str(response)
        if context and context.strip():
            return f"\n\n--- RELEVANT KNOWLEDGE GRAPH CONTEXT ---\n{context[:3000]}\n--- END CONTEXT ---"
    except Exception as exc:
        logger.warning("graph_context_retrieval_failed", error=str(exc))
    return ""


async def chat_stream(
    expert: Expert,
    user_message: str,
    use_graph: bool = True,
) -> AsyncIterator[str]:
    if expert.status != ExpertStatus.READY:
        raise ExpertNotFoundError(expert.slug)

    conversation = get_or_create_conversation(expert.slug)
    conversation.add_message("user", user_message)

    graph_context = ""
    if use_graph:
        graph_context = await _retrieve_graph_context(expert, user_message)

    system_prompt = build_expert_system_prompt(expert.topic, expert.description)
    if graph_context:
        system_prompt += graph_context

    history = conversation.messages[-(1 + _MAX_HISTORY_MESSAGES) : -1]
    messages = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]
    messages.append({"role": "user", "content": user_message})

    full_response: list[str] = []
    try:
        async for chunk in stream_completion(
            system_prompt=system_prompt,
            messages=messages,
        ):
            full_response.append(chunk)
            yield chunk

        conversation.add_message("assistant", "".join(full_response))
        logger.info(
            "chat_turn_complete",
            slug=expert.slug,
            turns=len(conversation.messages),
        )

    except Exception as exc:
        logger.error("chat_stream_failed", slug=expert.slug, error=str(exc))
        raise ConversationError(f"Chat failed for '{expert.slug}': {exc}") from exc
