"""Provider clients are constructed with an explicit timeout budget.

The SDK default is ten minutes. A composition call that takes ten minutes to
fail does not fail alone — it holds the SSE connection, the conversation's
streaming claim, and a pooled database connection with it. Nothing about that is
visible in a code review of the call site, which is why it is asserted here.
"""

from unittest.mock import patch

from peritus.core.config import settings
from peritus.infrastructure import anthropic_client


def _construct_with_captured_kwargs() -> dict:
    captured: dict = {}

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch.object(anthropic_client, "_client", None), \
         patch.object(anthropic_client.anthropic, "AsyncAnthropic", _FakeAnthropic):
        anthropic_client.get_anthropic_client()
    return captured


def test_anthropic_client_has_a_bounded_timeout():
    kwargs = _construct_with_captured_kwargs()
    assert kwargs["timeout"] == settings.ANTHROPIC_TIMEOUT
    assert settings.ANTHROPIC_TIMEOUT < 600, "must be tighter than the SDK default"


def test_anthropic_client_keeps_retries_on():
    """Transient 429s and 5xx are normal at this traffic shape; the bounded
    timeout is meant to fail fast *per attempt*, not to give up on the request."""
    kwargs = _construct_with_captured_kwargs()
    assert kwargs["max_retries"] == settings.ANTHROPIC_MAX_RETRIES
    assert settings.ANTHROPIC_MAX_RETRIES >= 1


def test_worst_case_wait_stays_under_the_batch_poll_interval():
    """A stalled call must resolve well inside the build worker's heartbeat
    cadence, or a healthy build looks like a crashed one to the reaper."""
    worst_case = settings.ANTHROPIC_TIMEOUT * (1 + settings.ANTHROPIC_MAX_RETRIES)
    assert worst_case < settings.ANTHROPIC_BATCH_TIMEOUT


def test_anthropic_client_is_a_singleton():
    with patch.object(anthropic_client, "_client", None):
        first = anthropic_client.get_anthropic_client()
        assert anthropic_client.get_anthropic_client() is first


def test_openai_timeout_is_bounded():
    assert settings.OPENAI_TIMEOUT < 600
    assert settings.OPENAI_MAX_RETRIES >= 1
