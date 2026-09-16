"""Gutenberg discovery without depending on Gutendex.

Job 53 got zero Gutenberg candidates because Gutendex timed out under a single
45-second budget that returned nothing, and the build log said `gutenberg: 0`.
"""

from unittest.mock import AsyncMock, patch

import pytest

from peritus.infrastructure.gutenberg_catalogue import GutenbergCatalogue
from peritus.sources.fetchers import gutenberg as module
from peritus.sources.fetchers.base import STATUS_TIMEOUT, begin_search_note, end_search_note

_CSV = """Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves
2680,Text,2001-01-01,Meditations,en,"Marcus Aurelius, Emperor of Rome, 121-180",Stoics; Ethics,,
"""

_BOOKS = [
    {"title": "Meditations", "author": "Marcus Aurelius", "search_query": "Aurelius"},
    {"title": "Enchiridion", "author": "Epictetus", "search_query": "Epictetus"},
    {"title": "Letters from a Stoic", "author": "Seneca", "search_query": "Seneca"},
]


@pytest.mark.asyncio
async def test_the_catalogue_resolves_books_with_no_gutendex_call():
    gutendex = AsyncMock(return_value=([], False))
    with (
        patch.object(module, "_identify_books", AsyncMock(return_value=_BOOKS[:1])),
        patch.object(
            module, "load_catalogue", AsyncMock(return_value=GutenbergCatalogue.from_csv_text(_CSV))
        ),
        patch.object(module, "_search_gutendex", gutendex),
    ):
        [candidate] = await module.GutenbergFetcher().search("stoicism")
    assert candidate.url == "https://www.gutenberg.org/ebooks/2680"
    assert candidate.metadata["gutenberg_id"] == 2680
    gutendex.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_gutendex_timeout_costs_its_own_book_not_the_ones_already_resolved():
    async def _gutendex(client, query, limit):
        if query == "Epictetus":
            return [], True  # timed out
        return [
            {"id": 45109, "title": "Letters from a Stoic", "authors": [{"name": "Seneca"}]}
        ], False

    with (
        patch.object(module, "_identify_books", AsyncMock(return_value=_BOOKS)),
        patch.object(
            module, "load_catalogue", AsyncMock(return_value=GutenbergCatalogue.from_csv_text(_CSV))
        ),
        patch.object(module, "_search_gutendex", _gutendex),
    ):
        candidates = await module.GutenbergFetcher().search("stoicism")
    assert [c.metadata["gutenberg_id"] for c in candidates] == [2680, 45109]


@pytest.mark.asyncio
async def test_an_all_timeout_search_reports_a_timeout_not_an_empty_topic():
    note, token = begin_search_note()
    try:
        with (
            patch.object(module, "_identify_books", AsyncMock(return_value=_BOOKS[1:2])),
            patch.object(module, "load_catalogue", AsyncMock(return_value=None)),
            patch.object(module, "_search_gutendex", AsyncMock(return_value=([], True))),
        ):
            assert await module.GutenbergFetcher().search("stoicism") == []
    finally:
        end_search_note(token)
    assert [status for status, _ in note.failures] == [STATUS_TIMEOUT]
