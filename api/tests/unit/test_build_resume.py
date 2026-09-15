"""Where a retried build job picks up (``jobs/worker._resume_point``)."""

from types import SimpleNamespace

from peritus.jobs.worker import _resume_point
from peritus.search.readiness import Readiness


class _Resumable:
    async def build(self, expert, on_event=None): ...
    async def resume(self, expert, from_readiness, on_event=None): ...


class _BuildOnly:
    async def build(self, expert, on_event=None): ...


def _job(attempts: int):
    return SimpleNamespace(attempts=attempts)


def _expert(readiness: str):
    return SimpleNamespace(readiness=readiness)


def test_first_attempt_always_starts_clean():
    # A rebuild of an already-ready expert is attempt 1 and must reset.
    assert _resume_point(_job(1), _expert("graph_ready"), _Resumable()) is None


def test_retry_resumes_from_recorded_readiness():
    assert _resume_point(_job(2), _expert("graph_ready"), _Resumable()) is Readiness.GRAPH_READY
    assert _resume_point(_job(3), _expert("chat_ready"), _Resumable()) is Readiness.CHAT_READY


def test_retry_before_chat_ready_starts_clean():
    assert _resume_point(_job(2), _expert("pending"), _Resumable()) is None
    assert _resume_point(_job(2), _expert("nonsense"), _Resumable()) is None


def test_builder_without_resume_starts_clean():
    assert _resume_point(_job(2), _expert("graph_ready"), _BuildOnly()) is None
