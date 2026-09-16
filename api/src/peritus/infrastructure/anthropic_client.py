"""The shared Anthropic client.

Constructed with an explicit timeout and retry budget rather than the SDK's
defaults. The default request timeout is ten minutes, and a composition call
that takes ten minutes to fail does not fail alone: it holds the SSE connection,
the conversation's streaming claim, and — through the retrieval that preceded it
— a slot in every downstream budget. Bounding the call turns a provider stall
into a fast, retryable error.

Retries stay on (transient 429/5xx are normal at this traffic shape) and the SDK
applies them per attempt, so the worst case a caller waits is roughly
``ANTHROPIC_TIMEOUT × (1 + ANTHROPIC_MAX_RETRIES)`` plus backoff.
"""

from typing import Any

import anthropic
from anthropic.types import Message, ToolUseBlock

from peritus.core.config import settings

_client: anthropic.AsyncAnthropic | None = None


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=settings.ANTHROPIC_TIMEOUT,
            max_retries=settings.ANTHROPIC_MAX_RETRIES,
        )
    return _client


def tool_input(response: Message) -> dict[str, Any] | None:
    """The arguments of the first tool call in ``response``, or None.

    Eighteen call sites picked the block out by hand with
    ``next(b for b in resp.content if getattr(b, "type", None) == "tool_use")``,
    and that `getattr` is why: `content` is a union of thirteen block types and
    only one of them has `.input`, so nothing could narrow it and every one of
    those sites needed a `# type: ignore` to compile. An ignore on a model call
    silences the *real* mistakes too — a misspelled parameter, a message in the
    wrong shape — which is the cost that matters.

    `isinstance` narrows properly, so the boundary is typed once here and the
    ignores go away everywhere.

    None rather than raising when the model answered with prose instead of
    calling the tool. That is a real outcome — a refusal, a truncated response —
    and every caller already has to decide what to do about it.
    """
    for block in response.content:
        if isinstance(block, ToolUseBlock):
            # `input` is `object` in the SDK because it is whatever the tool's
            # schema says. A dict is what every tool here declares.
            return dict(block.input) if isinstance(block.input, dict) else None
    return None
