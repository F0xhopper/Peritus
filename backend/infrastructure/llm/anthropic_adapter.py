"""Anthropic Claude adapter for LlamaIndex and direct completions."""

from __future__ import annotations

from typing import AsyncIterator

import anthropic
from llama_index.llms.anthropic import Anthropic as LlamaAnthropic

from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)


def get_llama_llm() -> LlamaAnthropic:
    """Return a LlamaIndex-compatible Anthropic LLM."""
    settings = get_settings()
    return LlamaAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=8192,
    )


def get_anthropic_client() -> anthropic.Anthropic:
    """Return a raw Anthropic client for direct API calls."""
    settings = get_settings()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def stream_completion(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
) -> AsyncIterator[str]:
    """
    Stream a completion from Claude, yielding text chunks.

    Args:
        system_prompt: The system persona / instruction.
        messages: List of {"role": "user"|"assistant", "content": str}.
        model: Override model; defaults to settings.anthropic_model.

    Yields:
        Text delta strings as they arrive.
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    chosen_model = model or settings.anthropic_model

    async with client.messages.stream(
        model=chosen_model,
        system=system_prompt,
        messages=messages,
        max_tokens=8192,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def complete(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
) -> str:
    """
    Non-streaming completion from Claude.

    Returns:
        Full response text.
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    chosen_model = model or settings.anthropic_model

    response = await client.messages.create(
        model=chosen_model,
        system=system_prompt,
        messages=messages,
        max_tokens=8192,
    )
    return response.content[0].text


def build_expert_system_prompt(topic: str, description: str) -> str:
    """Build the system prompt that gives the expert its persona."""
    return f"""You are Peritus – a world-class domain expert in "{topic}".

Your knowledge base was assembled from authoritative academic papers, technical documentation, and expert sources. You have a deep, structured understanding of this topic represented as a knowledge graph.

{description}

When answering:
- Be precise, authoritative, and educational.
- Cite concepts from your knowledge base when possible.
- Structure long answers with clear headings and bullet points.
- If generating code, wrap it in triple-backtick fences with the language tag.
- If asked about something outside "{topic}", politely redirect the learner back to the topic.
- Speak as an expert mentor, not a general assistant.

Your goal is to make the learner deeply understand "{topic}" through clear explanations, examples, analogies, and guided discovery."""
