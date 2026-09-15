"""Answer composition must leave room for the answer.

Claude Sonnet 5 thinks unless told otherwise, and its thinking counts against
max_tokens. Sent the tier's answer length as the whole budget, the first
question to a new expert spent it all thinking and produced no text — the
conversation stored the question with nothing under it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from peritus.chat.agent import composition_params
from peritus.core.config import settings


def test_a_thinking_model_gets_headroom_and_an_explicit_effort(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_EFFORT", "low")
    monkeypatch.setattr(settings, "CHAT_THINKING_HEADROOM_TOKENS", 4096)
    params = composition_params("claude-sonnet-5", 2048)
    assert params == {
        "max_tokens": 2048 + 4096,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "low"},
    }


def test_a_model_without_adaptive_thinking_gets_the_plain_request():
    assert composition_params("claude-haiku-4-5-20251001", 1024) == {"max_tokens": 1024}


@pytest.mark.asyncio
async def test_an_answer_with_no_text_raises_instead_of_ending_quietly():
    from peritus.chat import streaming
    from peritus.chat.agent import RetrievedContext

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def _none():
                if False:
                    yield ""
            return _none()

        async def get_final_message(self):
            return SimpleNamespace(stop_reason="max_tokens")

    ctx = MagicMock(spec=RetrievedContext)
    ctx.context_block, ctx.plan, ctx.has_contradiction, ctx.contradiction_points = "", None, False, []

    class _Agent:
        def __init__(self, _pool):
            pass

        async def retrieve(self, *_args):
            yield "context", ctx

    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_Stream())
    expert = SimpleNamespace(id=1, topic="t", persona_style=None, config=SimpleNamespace(max_response_tokens=2048))

    with (
        patch.object(streaming, "ChatAgent", _Agent),
        patch.object(streaming, "get_anthropic_client", lambda: client),
        patch.object(streaming, "build_composition_messages", lambda *a, **k: []),
        patch.object(streaming, "build_cached_system", lambda *a, **k: []),
        pytest.raises(streaming.EmptyAnswerError, match="max_tokens"),
    ):
        async for _event in streaming.stream_expert_answer(MagicMock(), expert, "q", []):
            pass
    assert client.messages.stream.call_args.kwargs["max_tokens"] > 2048
