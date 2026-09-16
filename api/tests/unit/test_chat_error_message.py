"""What a reader is told when an answer dies mid-stream.

The property under test is not the wording — it is that a **provider refusal is
not reported as an internal error**. An empty credit balance, a revoked key and
a rate limit all arrive as an ``anthropic.APIStatusError``, and the one sentence
that says how to fix any of them is the provider's own. The build path has always
surfaced it (``provider_error_message``); chat replied "the expert hit an
internal error while answering" and left the owner guessing between a billing
problem and a bug in retrieval.
"""

import httpx
import pytest
from anthropic import APIStatusError

from peritus.api.routes.conversations import answer_error_message


def _status_error(status: int, message: str) -> APIStatusError:
    """An SDK error shaped the way the SDK shapes one."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return APIStatusError(
        message,
        response=httpx.Response(status, request=request, json=body),
        body=body,
    )


def test_a_provider_refusal_quotes_the_provider():
    error = _status_error(400, "Your credit balance is too low to access the Anthropic API.")
    text = answer_error_message(error)
    assert "Anthropic API rejected the request" in text
    assert "credit balance is too low" in text
    # And it does not call a billing problem a bug.
    assert "internal error" not in text


@pytest.mark.parametrize("status", [401, 429, 500, 529])
def test_every_provider_status_is_attributed_to_the_provider(status: int):
    text = answer_error_message(_status_error(status, "nope"))
    assert "Anthropic" in text


def test_a_long_provider_message_is_trimmed_to_a_notice():
    text = answer_error_message(_status_error(400, "x" * 1000))
    assert len(text) < 400


def test_anything_else_is_still_an_internal_error():
    # A retrieval bug, a database blip, a None where a list was expected: the
    # reader learns nothing from a stack trace and the log has the detail.
    assert answer_error_message(ValueError("boom")) == (
        "The expert hit an internal error while answering."
    )
