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

import anthropic

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
