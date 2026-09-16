"""DB-backed tests for ``ExpertPictureRepository`` (migration 027).

Four things here are Postgres behaviour a mock cannot check: that the blob
round-trips as bytes, that the picture joins onto every expert query without
the image coming with it, that deleting an expert takes its picture, and — the
one that would be a silent data-loss bug — that ``reset_build_state`` leaves the
picture alone, because a rebuild must not throw away a picture the owner may
have chosen.

Requires PERITUS_TEST_DATABASE_URL; skips otherwise via the ``db_pool`` fixture.
"""

import pytest

from peritus.experts.domain import ExpertTier
from peritus.experts.picture import FoundPicture
from peritus.experts.picture_repository import ExpertPictureRepository
from peritus.experts.repository import ExpertRepository

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8


def _found(sha: str = "c" * 64, license_name: str = "Public domain") -> FoundPicture:
    return FoundPicture(
        image=JPEG,
        content_type="image/jpeg",
        width=512,
        height=683,
        sha256=sha,
        provider="wikipedia",
        file_name="File:Zeno_of_Citium.jpg",
        file_url="https://upload.wikimedia.org/thumb/512px-Zeno.jpg",
        file_page_url="https://commons.wikimedia.org/wiki/File:Zeno_of_Citium.jpg",
        page_url="https://en.wikipedia.org/wiki/Stoicism",
        page_title="Zeno of Citium",
        artist="Paolo Monti",
        license=license_name,
        license_url="https://creativecommons.org/publicdomain/mark/1.0/",
        query="Stoicism",
        candidates=[{"page_title": "Stoicism", "file_name": "File:Zeno.jpg"}],
    )


async def _make_expert(db_pool, name="stoicism"):
    return await ExpertRepository(db_pool).create(
        name=name, topic="Stoicism", tier=ExpertTier.LITE, owner_id=OWNER
    )


@pytest.mark.asyncio
async def test_upsert_then_read_round_trips_the_bytes_and_the_provenance(db_pool):
    expert = await _make_expert(db_pool)
    pictures = ExpertPictureRepository(db_pool)

    await pictures.upsert(expert.id, _found())

    blob = await pictures.get_blob(expert.id)
    assert blob is not None
    image, content_type, sha = blob
    assert image == JPEG
    assert content_type == "image/jpeg"
    assert sha == "c" * 64

    record = await pictures.get(expert.id)
    assert record is not None
    assert record.page_title == "Zeno of Citium"
    assert record.artist == "Paolo Monti"
    assert record.version == "c" * 12
    assert record.attribution_required is False
    assert record.chosen_by == "build"

    assert await pictures.get_candidates(expert.id) == [
        {"page_title": "Stoicism", "file_name": "File:Zeno.jpg"}
    ]


@pytest.mark.asyncio
async def test_upsert_replaces_rather_than_duplicating(db_pool):
    """Both callers that produce a picture are re-runnable; the key is the expert."""
    expert = await _make_expert(db_pool)
    pictures = ExpertPictureRepository(db_pool)

    await pictures.upsert(expert.id, _found())
    await pictures.upsert(
        expert.id, _found(sha="d" * 64, license_name="CC BY-SA 4.0"), chosen_by="owner"
    )

    record = await pictures.get(expert.id)
    assert record is not None
    assert record.sha256 == "d" * 64
    assert record.chosen_by == "owner"
    assert record.attribution_required is True


@pytest.mark.asyncio
async def test_the_picture_joins_onto_expert_reads_without_the_bytes(db_pool):
    expert = await _make_expert(db_pool)
    await ExpertPictureRepository(db_pool).upsert(expert.id, _found())
    repo = ExpertRepository(db_pool)

    for read in (
        await repo.get_by_id(expert.id),
        await repo.get_by_name("stoicism"),
        await repo.get_for_user("stoicism", OWNER, include_unowned=False),
        await repo.get_owned_for_user("stoicism", OWNER, include_unowned=False),
    ):
        assert read is not None
        assert read.picture is not None
        assert read.picture.page_title == "Zeno of Citium"

    listed = await repo.list_for_user(OWNER, include_unowned=False)
    assert listed[0].picture is not None
    # The domain object has no field for the image, which is the guarantee: a
    # list query physically cannot carry 100 KB a row.
    assert not hasattr(listed[0].picture, "image")


@pytest.mark.asyncio
async def test_an_expert_without_a_picture_reads_as_none(db_pool):
    expert = await _make_expert(db_pool)
    read = await ExpertRepository(db_pool).get_by_id(expert.id)
    assert read is not None
    assert read.picture is None


@pytest.mark.asyncio
async def test_a_rebuild_does_not_throw_the_picture_away(db_pool):
    """`reset_build_state` wipes the corpus. It must not wipe this."""
    expert = await _make_expert(db_pool)
    pictures = ExpertPictureRepository(db_pool)
    await pictures.upsert(expert.id, _found())

    await ExpertRepository(db_pool).reset_build_state(expert.id)

    assert await pictures.exists(expert.id) is True


@pytest.mark.asyncio
async def test_deleting_an_expert_takes_its_picture_with_it(db_pool):
    expert = await _make_expert(db_pool)
    pictures = ExpertPictureRepository(db_pool)
    await pictures.upsert(expert.id, _found())

    await ExpertRepository(db_pool).delete(expert.id)

    assert await pictures.get_blob(expert.id) is None


@pytest.mark.asyncio
async def test_delete_removes_only_the_picture(db_pool):
    expert = await _make_expert(db_pool)
    pictures = ExpertPictureRepository(db_pool)
    await pictures.upsert(expert.id, _found())

    assert await pictures.delete(expert.id) is True
    assert await pictures.delete(expert.id) is False  # idempotent
    assert await ExpertRepository(db_pool).get_by_id(expert.id) is not None


@pytest.mark.asyncio
async def test_list_missing_is_the_backfills_worklist(db_pool):
    with_picture = await _make_expert(db_pool, name="stoicism")
    without = await _make_expert(db_pool, name="thomism")
    await ExpertPictureRepository(db_pool).upsert(with_picture.id, _found())

    missing = await ExpertPictureRepository(db_pool).list_missing(limit=50)

    ids = [row[0] for row in missing]
    assert without.id in ids
    assert with_picture.id not in ids
