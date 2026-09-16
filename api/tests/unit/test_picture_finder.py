"""``find_picture`` end to end, against a fake Wikimedia.

No network, and deliberately so: the suite has to be able to assert "a topic
whose only article is about a living person falls through to the next one"
without that depending on who happens to be alive when it runs.

Every payload below is the shape the real Action API returns — the same nesting,
the same ``extmetadata`` wrapper, the same negative page ids — so a fixture that
drifts from the API is a test failure rather than a production surprise.
"""

import asyncio

import pytest

from peritus.experts.picture import PictureSkipped, find_picture
from peritus.infrastructure.wikimedia import normalise_title

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 2048


def _page(
    pageid: int,
    title: str,
    file_name: str | None,
    *,
    qid: str | None = None,
    disambiguation: bool = False,
    original: tuple[int, int] = (900, 1200),
) -> dict:
    page: dict = {"pageid": pageid, "title": title, "pageprops": {}}
    if qid:
        page["pageprops"]["wikibase_item"] = qid
    if disambiguation:
        page["pageprops"]["disambiguation"] = ""
    if file_name:
        page["pageimage"] = file_name
        page["thumbnail"] = {
            "source": f"https://upload.wikimedia.org/thumb/{file_name}/512px.jpg",
            "width": 512,
            "height": 512,
        }
        page["original"] = {"width": original[0], "height": original[1]}
    return page


def _imageinfo(license_name: str = "Public domain", *, artist: str = "Unknown") -> dict:
    return {
        "mime": "image/jpeg",
        "thumburl": "https://upload.wikimedia.org/thumb/512px.jpg",
        "thumbwidth": 512,
        "thumbheight": 683,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "extmetadata": {
            "LicenseShortName": {"value": license_name},
            "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/mark/1.0/"},
            "Artist": {"value": f'<a href="/wiki/User:X">{artist}</a>'},
            "Restrictions": {"value": ""},
        },
    }


def _human(died: bool) -> dict:
    claims: dict = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}
    if died:
        claims["P570"] = [{"mainsnak": {"datavalue": {"value": {"time": "+0262-01-01"}}}}]
    return claims


class FakeWikimedia:
    """Records what was asked and replays canned answers."""

    def __init__(
        self,
        *,
        search: dict[str, list[str]] | None = None,
        pages: list[dict] | None = None,
        claims: dict[str, dict] | None = None,
        infos: dict[str, dict] | None = None,
        downloads: dict[str, bytes | None] | None = None,
        stall: float = 0.0,
    ) -> None:
        self._search = search or {}
        self._pages = pages or []
        self._claims = claims or {}
        self._infos = infos or {}
        self._downloads = downloads if downloads is not None else {}
        self._stall = stall
        self.downloaded: list[str] = []

    async def search_articles(self, query: str, limit: int = 3) -> list[str]:
        if self._stall:
            await asyncio.sleep(self._stall)
        return self._search.get(query, [])[:limit]

    async def page_images(self, titles, thumb_size: int = 512):
        return [p for p in self._pages if p["title"] in titles]

    async def wikidata_claims(self, entity_ids):
        return {q: self._claims.get(q, {}) for q in entity_ids}

    async def image_info(self, file_titles, thumb_width: int = 512):
        # Keyed the way the real endpoint keys it: the canonical title, with
        # spaces, whatever underscored form was asked for. A fake that echoed
        # the caller's spelling would have hidden the bug this models.
        wanted = {normalise_title(t) for t in file_titles}
        return {
            normalise_title(t): info
            for t, info in self._infos.items()
            if normalise_title(t) in wanted
        }

    async def download(self, url: str, max_bytes: int):
        self.downloaded.append(url)
        # Default: every download works, so a test only spells out the failures.
        return self._downloads.get(url, JPEG) if self._downloads else JPEG


@pytest.mark.asyncio
async def test_picks_the_lead_image_of_the_topics_own_article():
    client = FakeWikimedia(
        search={"Stoicism": ["Stoicism", "Zeno of Citium"], "virtue": ["Virtue"]},
        pages=[
            _page(1, "Stoicism", "Zeno_of_Citium_Pushkin.jpg", qid="Q22647"),
            _page(2, "Zeno of Citium", "Zeno_bust.jpg", qid="Q168261"),
            _page(3, "Virtue", "Virtue_allegory.jpg", qid="Q1"),
        ],
        claims={"Q168261": _human(died=True)},
        infos={
            "File:Zeno_of_Citium_Pushkin.jpg": _imageinfo(artist="Paolo Monti"),
            "File:Zeno_bust.jpg": _imageinfo(),
            "File:Virtue_allegory.jpg": _imageinfo(),
        },
    )

    found = await find_picture(client, "Stoicism", ["virtue"])

    assert found.page_title == "Stoicism"
    assert found.provider == "wikipedia"
    assert found.content_type == "image/jpeg"
    assert found.license == "Public domain"
    # The HTML around a credit is stripped before it is stored.
    assert found.artist == "Paolo Monti"
    assert found.sha256 and found.version == found.sha256[:12]
    # The shortlist is kept for the picker, as metadata only.
    assert len(found.candidates) == 3
    assert all("image" not in c for c in found.candidates)


@pytest.mark.asyncio
async def test_a_disambiguation_page_is_never_the_picture():
    client = FakeWikimedia(
        search={"Mercury": ["Mercury", "Mercury (planet)"]},
        pages=[
            _page(1, "Mercury", "Mercury_disambig.jpg", disambiguation=True),
            _page(2, "Mercury (planet)", "Mercury_in_true_color.jpg", qid="Q308"),
        ],
        infos={
            "File:Mercury_disambig.jpg": _imageinfo(),
            "File:Mercury_in_true_color.jpg": _imageinfo(),
        },
    )

    found = await find_picture(client, "Mercury", [])

    assert found.page_title == "Mercury (planet)"


@pytest.mark.asyncio
async def test_a_living_person_falls_through_to_the_next_article():
    client = FakeWikimedia(
        search={"Loop quantum gravity": ["Carlo Rovelli", "Loop quantum gravity"]},
        pages=[
            _page(1, "Carlo Rovelli", "Carlo_Rovelli_2019.jpg", qid="Q313565"),
            _page(2, "Loop quantum gravity", "Spin_network.jpg", qid="Q622477"),
        ],
        claims={"Q313565": _human(died=False)},
        infos={
            "File:Carlo_Rovelli_2019.jpg": _imageinfo("CC BY-SA 4.0"),
            "File:Spin_network.jpg": _imageinfo(),
        },
    )

    found = await find_picture(client, "Loop quantum gravity", [])

    assert found.page_title == "Loop quantum gravity"


@pytest.mark.asyncio
async def test_a_topic_whose_images_are_all_marks_gets_no_picture():
    client = FakeWikimedia(
        search={"Flag protocol": ["Flag of Japan", "Flag of France"]},
        pages=[
            _page(1, "Flag of Japan", "Flag_of_Japan.png"),
            _page(2, "Flag of France", "Flag_of_France.png"),
        ],
    )

    with pytest.raises(PictureSkipped) as exc:
        await find_picture(client, "Flag protocol", [])
    assert exc.value.reason == "no_candidate"


@pytest.mark.asyncio
async def test_a_non_free_licence_is_refused_even_when_the_article_is_right():
    client = FakeWikimedia(
        search={"Some album": ["Some album"]},
        pages=[_page(1, "Some album", "Cover_art.jpg")],
        infos={"File:Cover_art.jpg": _imageinfo("Fair use")},
    )

    with pytest.raises(PictureSkipped) as exc:
        await find_picture(client, "Some album", [])
    assert exc.value.reason == "no_candidate"


@pytest.mark.asyncio
async def test_a_tiny_original_is_not_worth_cropping_to_a_square():
    client = FakeWikimedia(
        search={"Obscure topic": ["Obscure topic"]},
        pages=[_page(1, "Obscure topic", "Tiny.jpg", original=(120, 90))],
        infos={"File:Tiny.jpg": _imageinfo()},
    )

    with pytest.raises(PictureSkipped) as exc:
        await find_picture(client, "Obscure topic", [])
    assert exc.value.reason == "no_candidate"


@pytest.mark.asyncio
async def test_an_oversized_file_falls_through_to_the_next_candidate():
    """A too-large first pick must not cost the expert its picture."""
    big = "https://upload.wikimedia.org/thumb/Huge.jpg/512px.jpg"
    client = FakeWikimedia(
        search={"Stoicism": ["Stoicism", "Zeno of Citium"]},
        pages=[
            _page(1, "Stoicism", "Huge.jpg"),
            _page(2, "Zeno of Citium", "Small.jpg"),
        ],
        infos={
            "File:Huge.jpg": {**_imageinfo(), "thumburl": big},
            "File:Small.jpg": {
                **_imageinfo(),
                "thumburl": "https://upload.wikimedia.org/thumb/Small.jpg/512px.jpg",
            },
        },
        downloads={big: None},
    )

    found = await find_picture(client, "Stoicism", [])

    assert found.page_title == "Zeno of Citium"
    assert client.downloaded[0] == big  # the better-ranked one was tried first


@pytest.mark.asyncio
async def test_bytes_that_are_not_an_image_are_refused():
    client = FakeWikimedia(
        search={"Topic": ["Topic"]},
        pages=[_page(1, "Topic", "Broken.jpg")],
        infos={"File:Broken.jpg": _imageinfo()},
        # Keyed on the `pageimages` thumbnail, which is the URL actually
        # fetched — `imageinfo`'s `thumburl` can be the unscaled original.
        downloads={"https://upload.wikimedia.org/thumb/Broken.jpg/512px.jpg": b"<html>404</html>"},
    )

    with pytest.raises(PictureSkipped) as exc:
        await find_picture(client, "Topic", [])
    assert exc.value.reason == "too_large"


@pytest.mark.asyncio
async def test_no_search_hits_at_all():
    with pytest.raises(PictureSkipped) as exc:
        await find_picture(FakeWikimedia(), "A topic nothing knows about", [])
    assert exc.value.reason == "no_candidate"


@pytest.mark.asyncio
async def test_the_deadline_is_honoured_and_reported_as_a_timeout():
    """A slow Wikimedia is never the build's problem — it is this one's."""
    client = FakeWikimedia(search={"Stoicism": ["Stoicism"]}, stall=5.0)

    with pytest.raises(PictureSkipped) as exc:
        await find_picture(client, "Stoicism", [], deadline=0.05)
    assert exc.value.reason == "timeout"


@pytest.mark.asyncio
async def test_a_file_name_with_spaces_still_finds_its_licence():
    """`pageimages` says `Zeno_of_Citium.jpg`; `imageinfo` answers `Zeno of Citium.jpg`.

    Keying one endpoint's result by the other's spelling missed every file whose
    name contains a space — which is most of them — and the symptom was not an
    error but a silent "no freely licensed picture of this subject".
    """
    client = FakeWikimedia(
        search={"Beekeeping": ["Beekeeping"]},
        pages=[_page(1, "Beekeeping", "Beekeeper 2017 Honeybee Conservancy.jpg")],
        infos={"File:Beekeeper 2017 Honeybee Conservancy.jpg": _imageinfo("CC BY 2.0")},
    )

    found = await find_picture(client, "Beekeeping", [])

    assert found.page_title == "Beekeeping"
    assert found.license == "CC BY 2.0"


@pytest.mark.asyncio
async def test_the_pageimages_thumbnail_is_what_gets_fetched():
    """`imageinfo`'s `thumburl` is the original when MediaWiki cannot scale it.

    The two keys look interchangeable and are not: downloading a 12 MB collage
    instead of the 60 KB thumbnail `pageimages` already produced is how an
    expert loses its picture to the size cap. Observed on "Production Machine
    Learning", whose only candidate came back as an unscaled original.
    """
    client = FakeWikimedia(
        search={"Systems engineering": ["Systems engineering"]},
        pages=[_page(1, "Systems engineering", "Collage.jpg")],
        infos={
            "File:Collage.jpg": {
                **_imageinfo(),
                # No `/thumb/` segment: this is the full-size original.
                "thumburl": "https://upload.wikimedia.org/commons/8/85/Collage.jpg",
            }
        },
    )

    found = await find_picture(client, "Systems engineering", [])

    assert found.file_url == "https://upload.wikimedia.org/thumb/Collage.jpg/512px.jpg"
    assert client.downloaded == [found.file_url]


def test_a_syllabus_line_is_reduced_to_the_subject_it_is_about():
    """The planner writes concepts as prose; a search wants a subject.

    Handed the raw line, Wikipedia's full-text search matches on shared words
    and returns whatever is longest — which is how an expert on Aristotelian
    logic was nearly illustrated with a Susan Sontag essay collection.
    """
    from peritus.experts.picture import build_queries

    queries = build_queries(
        "Production Machine Learning",
        [
            "ML system design lifecycle (data collection through deployment and monitoring)",
            "Feature engineering and feature stores for production consistency",
        ],
    )

    # The topic runs first and verbatim — it is already a subject.
    assert queries[0] == "Production Machine Learning"
    assert queries[1] == "ML system design lifecycle"
    assert all(len(q) <= 60 for q in queries)
    assert not any("(" in q for q in queries)


def test_source_titles_are_used_verbatim_because_they_are_already_titles():
    from peritus.experts.picture import build_queries

    queries = build_queries("Stoicism", [], hints=("Zeno of Citium, founder of the Stoa",))
    assert queries == ["Stoicism", "Zeno of Citium, founder of the Stoa"]


@pytest.mark.asyncio
async def test_every_query_gets_a_hit_before_any_query_gets_a_second():
    """Concatenating spends the whole title budget on the first two queries.

    Observed on a real expert: "Aristotelian logic" and "On Interpretation"
    between them filled all eight slots, so "Organon" — whose lead image is a
    13th-century manuscript of the Categories — was never searched at all, and
    the picture the build settled for came from a Susan Sontag dust jacket that
    happened to share a word with one of the queries.
    """
    client = FakeWikimedia(
        search={
            "Aristotelian logic": ["Term logic", "Islamic logic", "Non-classical logic"],
            "On Interpretation": ["Interpretation", "On Interpretation", "Against Interpretation"],
            "Organon": ["Organon", "Categories", "Prior Analytics"],
        },
        # Only the one that concatenation would have missed has an image.
        pages=[_page(1, "Organon", "Aristotele_organon_XIII_secolo.jpg")],
        infos={"File:Aristotele_organon_XIII_secolo.jpg": _imageinfo()},
    )

    found = await find_picture(
        client, "Aristotelian logic", [], hints=("On Interpretation", "Organon")
    )

    assert found.page_title == "Organon"


@pytest.mark.asyncio
async def test_an_article_unrelated_to_what_was_searched_is_not_the_picture():
    """`is_on_topic` in the pipeline, not just as a unit.

    Both of these come back from a search for "On Interpretation" and both have
    a free lead image; only one of them is what the query was about.
    """
    client = FakeWikimedia(
        search={"Aristotelian logic": ["Ethics"], "On Interpretation": ["Against Interpretation"]},
        pages=[
            _page(1, "Ethics", "Aristotle_bust.jpg", qid="Q868"),
            _page(2, "Against Interpretation", "Sontag_dust_jacket.jpg"),
        ],
        infos={
            "File:Aristotle_bust.jpg": _imageinfo(),
            "File:Sontag_dust_jacket.jpg": _imageinfo(),
        },
    )

    found = await find_picture(client, "Aristotelian logic", [], hints=("On Interpretation",))

    # "Ethics" came from the topic's own search, which always has standing.
    assert found.page_title == "Ethics"
