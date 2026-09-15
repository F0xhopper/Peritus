"""Retry behaviour of the Wikimedia client.

This exists because of a real failure: the first backfill run against the live
API retried three times inside four seconds on a 429 and lost four experts out
of five. A 429 means "you personally are asking too often", and the only
backoff that can be right is the one the server asked for.
"""

import httpx
import pytest

from peritus.infrastructure.wikimedia import (
    _MAX_ATTEMPTS,
    _THROTTLE_WAIT,
    WikimediaClient,
    _retry_delay,
    user_agent,
)


def _response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(status, headers=headers, request=httpx.Request("GET", "https://x/"))


class TestRetryDelay:
    def test_prefers_what_the_server_asked_for(self):
        assert _retry_delay(_response(429, "30"), attempt=1) == 30.0

    def test_caps_an_unreasonable_ask(self):
        # Ten minutes is more than a build has; the caller degrades far cheaper.
        assert _retry_delay(_response(429, "600"), attempt=1) == 60.0

    def test_a_bare_429_still_waits_seconds_not_milliseconds(self):
        assert _retry_delay(_response(429), attempt=1) == _THROTTLE_WAIT
        # And escalates, so a second refusal is not met with the same rhythm.
        assert _retry_delay(_response(429), attempt=2) > _THROTTLE_WAIT

    def test_a_date_formatted_header_falls_back_rather_than_crashing(self):
        assert _retry_delay(_response(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 1) == _THROTTLE_WAIT

    def test_a_5xx_backs_off_faster_than_a_throttle(self):
        # A server error is a blip; a throttle is a decision about us.
        assert _retry_delay(_response(503), attempt=1) < _THROTTLE_WAIT


class TestGet:
    """Driven through a transport so the retry loop itself is exercised."""

    async def _client(self, handler, monkeypatch) -> WikimediaClient:
        client = WikimediaClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        # The waits are the point of the code, not of the test.
        monkeypatch.setattr("peritus.infrastructure.wikimedia.asyncio.sleep", _no_sleep)
        return client

    @pytest.mark.asyncio
    async def test_retries_a_throttle_and_returns_the_eventual_answer(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json={"query": {"search": [{"title": "Stoicism"}]}})

        client = await self._client(handler, monkeypatch)
        assert await client.search_articles("Stoicism") == ["Stoicism"]
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_gives_up_after_the_attempt_budget_rather_than_forever(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429)

        client = await self._client(handler, monkeypatch)
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_articles("Stoicism")
        assert calls["n"] == _MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_a_4xx_that_is_not_a_throttle_is_an_answer_not_a_blip(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(400)

        client = await self._client(handler, monkeypatch)
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_articles("Stoicism")
        assert calls["n"] == 1


class TestDownload:
    @pytest.mark.asyncio
    async def test_refuses_a_file_over_the_cap_mid_stream(self):
        """The cap is enforced on the bytes, not on the header it claims.

        A server is free to omit or lie about Content-Length, and the point of
        the cap is that a hostile or mistaken response cannot cost us memory.
        """
        def handler(request):
            return httpx.Response(200, content=b"x" * 5000)  # no Content-Length claim of ours

        client = WikimediaClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert await client.download("https://x/big.jpg", max_bytes=1000) is None
        assert await client.download("https://x/ok.jpg", max_bytes=10_000) == b"x" * 5000

    @pytest.mark.asyncio
    async def test_a_dead_link_is_none_rather_than_an_exception(self):
        """A picture is optional; a 404 on one must never reach the build."""
        client = WikimediaClient()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        )
        assert await client.download("https://x/gone.jpg", max_bytes=1000) is None


def test_the_user_agent_names_the_tool_and_carries_a_contact_when_set(monkeypatch):
    """Wikimedia's API policy asks for both; being unidentified is what gets 429s."""
    monkeypatch.setattr("peritus.infrastructure.wikimedia.settings.PERITUS_CONTACT", "")
    assert user_agent() == "Peritus/2.0 (research corpus builder)"

    monkeypatch.setattr(
        "peritus.infrastructure.wikimedia.settings.PERITUS_CONTACT", "ops@example.com"
    )
    assert "ops@example.com" in user_agent()
    assert user_agent().startswith("Peritus/2.0 ")


async def _no_sleep(_seconds: float) -> None:
    return None
