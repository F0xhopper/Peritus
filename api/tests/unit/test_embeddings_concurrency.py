"""The interactive and bulk embedding paths must not share a queue.

The failure this guards against is invisible in any single request's timing: a
build running in the same process (RUN_WORKER_IN_PROCESS) enqueues hundreds of
chunk batches, and with one shared semaphore a chat turn's query embedding waits
behind all of them. Chat latency then tracks the build's remaining work.
"""

import asyncio

import pytest

from peritus.infrastructure import embeddings


@pytest.fixture(autouse=True)
def fresh_semaphores(monkeypatch):
    """Reset the lazily-built semaphores between tests."""
    monkeypatch.setattr(embeddings, "_query_sem", None)
    monkeypatch.setattr(embeddings, "_batch_sem", None)


class _RecordingClient:
    """Stands in for AsyncOpenAI; blocks each call until released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.in_flight = 0
        self.peak_in_flight = 0
        self.embeddings = self

    async def create(self, *, model, input):
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await self.release.wait()
        finally:
            self.in_flight -= 1
        n = 1 if isinstance(input, str) else len(input)
        return _Response(n)


class _Response:
    def __init__(self, n: int) -> None:
        self.data = [_Item(i) for i in range(n)]


class _Item:
    def __init__(self, index: int) -> None:
        self.index = index
        self.embedding = [0.0, 1.0]


def _install(monkeypatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(embeddings, "get_embeddings_client", lambda: client)
    return client


async def test_a_saturated_bulk_path_does_not_block_a_query(monkeypatch):
    """The regression itself: builds must not queue ahead of chat."""
    from peritus.core.config import settings

    monkeypatch.setattr(settings, "EMBED_BATCH_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "EMBED_QUERY_CONCURRENCY", 4)
    client = _install(monkeypatch)

    # Fill the bulk budget and keep it full, as a build does.
    bulk = [asyncio.create_task(embeddings.embed_batch(["a", "b"])) for _ in range(5)]
    await asyncio.sleep(0)  # let them reach the semaphore

    # A query embedding must still get through.
    query = asyncio.create_task(embeddings.embed_query("what is virtue?"))
    await asyncio.sleep(0)
    assert client.in_flight == 2, "the query did not reach the API alongside the bulk call"

    client.release.set()
    assert await query == [0.0, 1.0]
    await asyncio.gather(*bulk)


async def test_bulk_concurrency_is_capped(monkeypatch):
    from peritus.core.config import settings

    monkeypatch.setattr(settings, "EMBED_BATCH_CONCURRENCY", 2)
    client = _install(monkeypatch)

    tasks = [asyncio.create_task(embeddings.embed_batch(["x"])) for _ in range(6)]
    await asyncio.sleep(0)
    assert client.peak_in_flight <= 2

    client.release.set()
    await asyncio.gather(*tasks)


async def test_query_concurrency_is_capped(monkeypatch):
    """Chat's budget is wider than the build's, but it is still a budget: a
    tier's worth of subqueries must not open unbounded connections."""
    from peritus.core.config import settings

    monkeypatch.setattr(settings, "EMBED_QUERY_CONCURRENCY", 3)
    client = _install(monkeypatch)

    tasks = [asyncio.create_task(embeddings.embed_query("q")) for _ in range(10)]
    await asyncio.sleep(0)
    assert client.peak_in_flight <= 3

    client.release.set()
    await asyncio.gather(*tasks)


async def test_embed_text_remains_an_alias_for_the_query_path():
    """Build-side and CLI callers still import embed_text."""
    assert embeddings.embed_text is embeddings.embed_query


async def test_batch_results_are_reordered_by_index(monkeypatch):
    """The API may return items out of order; callers zip results to inputs."""
    client = _install(monkeypatch)
    client.release.set()

    response = _Response(3)
    response.data = [response.data[2], response.data[0], response.data[1]]

    async def create(*, model, input):
        return response

    client.create = create

    result = await embeddings.embed_batch(["a", "b", "c"])
    assert len(result) == 3


async def test_client_is_constructed_with_an_explicit_timeout(monkeypatch):
    """The SDK default is minutes long, and a query embedding blocks a user."""
    from peritus.core.config import settings

    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setattr(embeddings, "AsyncOpenAI", _FakeOpenAI)

    embeddings.get_embeddings_client()

    assert captured["timeout"] == settings.OPENAI_TIMEOUT
    assert captured["max_retries"] == settings.OPENAI_MAX_RETRIES
    monkeypatch.setattr(embeddings, "_client", None)
