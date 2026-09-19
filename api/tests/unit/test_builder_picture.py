"""The build's picture hook: it reports, and it never interferes.

The one property worth a test is negative. Nothing about finding a picture may
fail a build, mark an expert not-ready, or touch ``experts.avatar`` — so these
drive ``_find_and_store_picture`` directly with a finder that succeeds, one that
comes up empty, and one that blows up, and assert that the only difference
visible to the build is which event was emitted.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.experts.builder import ExpertBuilder
from peritus.experts.domain import Expert, ExpertStatus, ExpertTier
from peritus.experts.picture import FoundPicture, PictureSkipped

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 32


def _expert() -> Expert:
    return Expert(
        id=7,
        name="stoic-philosophy",
        topic="Stoic philosophy",
        status=ExpertStatus.BUILDING,
        tier=ExpertTier.STANDARD,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _found() -> FoundPicture:
    return FoundPicture(
        image=JPEG,
        content_type="image/jpeg",
        width=512,
        height=683,
        sha256="b" * 64,
        provider="wikipedia",
        file_name="File:Zeno_of_Citium.jpg",
        file_url="https://upload.wikimedia.org/thumb/512px-Zeno.jpg",
        file_page_url="https://commons.wikimedia.org/wiki/File:Zeno_of_Citium.jpg",
        page_url="https://en.wikipedia.org/wiki/Stoicism",
        page_title="Zeno of Citium",
        artist="Paolo Monti",
        license="Public domain",
        license_url=None,
        query="Stoic philosophy",
    )


def _builder() -> tuple[ExpertBuilder, list[dict]]:
    builder = ExpertBuilder(MagicMock())
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    builder._on_event = on_event  # type: ignore[attr-defined]
    return builder, events


async def _run(builder, events, *, finder, exists: bool = False, pictures=None):
    repo = pictures or AsyncMock()
    repo.exists = AsyncMock(return_value=exists)
    repo.upsert = AsyncMock()
    with (
        patch("peritus.experts.builder.ExpertPictureRepository", return_value=repo),
        patch("peritus.experts.builder.WikimediaClient", return_value=_FakeClientCtx()),
        patch("peritus.experts.builder.find_picture", finder),
    ):
        await builder._find_and_store_picture(
            _expert(), "Stoic philosophy", ["virtue", "logos"], builder._on_event
        )
    return repo


class _FakeClientCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_a_found_picture_is_stored_and_announced():
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    repo = await _run(builder, events, finder=finder)

    repo.upsert.assert_awaited_once()
    assert repo.upsert.await_args.kwargs["chosen_by"] == "build"
    assert events == [
        {
            "type": "picture_ready",
            "provider": "wikipedia",
            "title": "Zeno of Citium",
            "page_url": "https://en.wikipedia.org/wiki/Stoicism",
            "license": "Public domain",
            "version": "b" * 12,
        }
    ]


@pytest.mark.asyncio
async def test_nothing_found_emits_a_reason_and_writes_nothing():
    builder, events = _builder()
    finder = AsyncMock(side_effect=PictureSkipped("no_candidate"))

    repo = await _run(builder, events, finder=finder)

    repo.upsert.assert_not_awaited()
    assert events == [{"type": "picture_skipped", "reason": "no_candidate"}]


@pytest.mark.asyncio
async def test_a_finder_that_raises_cannot_fail_the_build():
    """The whole point of the hook: an exception here is an event, not a raise."""
    builder, events = _builder()
    finder = AsyncMock(side_effect=RuntimeError("Wikimedia exploded"))

    repo = await _run(builder, events, finder=finder)

    repo.upsert.assert_not_awaited()
    assert events == [{"type": "picture_skipped", "reason": "provider_unavailable"}]


@pytest.mark.asyncio
async def test_a_rebuild_does_not_re_find_an_existing_picture():
    """The topic has not changed, and the owner may have chosen this one."""
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    repo = await _run(builder, events, finder=finder, exists=True)

    finder.assert_not_awaited()
    repo.upsert.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_the_feature_switch_says_so_rather_than_going_quiet():
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    with patch("peritus.experts.builder.settings.PICTURE_ENABLED", False):
        await builder._find_and_store_picture(_expert(), "Stoic philosophy", [], builder._on_event)

    finder.assert_not_awaited()
    assert events == [{"type": "picture_skipped", "reason": "disabled"}]


@pytest.mark.asyncio
async def test_cancellation_is_re_raised_rather_than_swallowed():
    """Cancellation is the worker shutting the build down, not a skip.

    Swallowing it would leave this coroutine alive after the build it belongs to
    has gone — and would make `picture_skipped` the last event of a cancelled
    build, which reads as a finished one.
    """
    builder, events = _builder()
    finder = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _run(builder, events, finder=finder)
    assert events == []


@pytest.mark.asyncio
async def test_awaiting_the_picture_never_blocks_a_finished_build():
    """`_await_picture` bounds the wait; a wedged task is abandoned, not waited on."""
    builder, _ = _builder()

    async def never() -> None:
        await asyncio.sleep(30)

    builder._picture_task = asyncio.create_task(never())
    with patch("peritus.experts.builder.settings.PICTURE_TIMEOUT", 0.05):
        await builder._await_picture()

    assert not builder._picture_task.done()
    builder._picture_task.cancel()


@pytest.mark.asyncio
async def test_awaiting_with_no_task_is_a_no_op():
    builder, _ = _builder()
    await builder._await_picture()


# ── the second look, at the end of the build ─────────────────────────────────


async def _retry(builder, *, finder, exists: bool, hints=("Thomism", "Summa Theologica")):
    repo = AsyncMock()
    repo.exists = AsyncMock(return_value=exists)
    repo.upsert = AsyncMock()
    repo.wikipedia_source_titles = (
        hints if isinstance(hints, AsyncMock) else AsyncMock(return_value=tuple(hints))
    )
    # The key concepts come off the row, not the plan: a resumed build never planned.
    stored = replace(_expert(), key_concepts=["act and potency"])
    builder._repo = MagicMock()
    builder._repo.get_by_id = AsyncMock(return_value=stored)
    with (
        patch("peritus.experts.builder.ExpertPictureRepository", return_value=repo),
        patch("peritus.experts.builder.WikimediaClient", return_value=_FakeClientCtx()),
        patch("peritus.experts.builder.find_picture", finder),
    ):
        await builder._retry_picture(_expert(), builder._on_event)
    return repo


@pytest.mark.asyncio
async def test_the_second_look_is_a_no_op_once_there_is_a_picture():
    """The common build: the first look served it, so nothing is searched again.

    Also what protects a rebuild — the picture that is there may be one the
    owner chose.
    """
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    repo = await _retry(builder, finder=finder, exists=True)

    finder.assert_not_awaited()
    repo.wikipedia_source_titles.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_the_second_look_searches_with_the_corpus_and_a_longer_deadline():
    """The case it exists for: `provider_unavailable` at second four of the build.

    The first look has no corpus; this one hands the finder the expert's own
    validated Wikipedia titles, and the deadline sized for a last chance.
    """
    from peritus.core.config import settings

    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    repo = await _retry(builder, finder=finder, exists=False)

    finder.assert_awaited_once()
    args, kwargs = finder.await_args
    assert args[1:] == (
        "Stoic philosophy",
        ["act and potency"],
        ("Thomism", "Summa Theologica"),
    )
    assert kwargs == {"deadline": settings.PICTURE_FINAL_TIMEOUT, "widen": True}
    assert settings.PICTURE_FINAL_TIMEOUT > settings.PICTURE_TIMEOUT
    repo.upsert.assert_awaited_once()
    assert [e["type"] for e in events] == ["picture_ready"]


@pytest.mark.asyncio
async def test_the_second_look_coming_up_empty_says_so_and_nothing_more():
    builder, events = _builder()
    finder = AsyncMock(side_effect=PictureSkipped("no_candidate"))

    repo = await _retry(builder, finder=finder, exists=False)

    repo.upsert.assert_not_awaited()
    assert events == [{"type": "picture_skipped", "reason": "no_candidate"}]


@pytest.mark.asyncio
async def test_the_second_look_still_runs_when_the_hints_cannot_be_read():
    """Hints improve the search; they are not a condition of it."""
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())
    broken = AsyncMock(side_effect=RuntimeError("connection reset"))

    await _retry(builder, finder=finder, exists=False, hints=broken)

    finder.assert_awaited_once()
    assert finder.await_args.args[3] == ()
    assert [e["type"] for e in events] == ["picture_ready"]


@pytest.mark.asyncio
async def test_the_second_look_is_silent_with_the_feature_off():
    """`disabled` was already said once, by the first look."""
    builder, events = _builder()
    finder = AsyncMock(return_value=_found())

    with patch("peritus.experts.builder.settings") as fake:
        fake.PICTURE_ENABLED = False
        await _retry(builder, finder=finder, exists=False)

    finder.assert_not_awaited()
    assert events == []
