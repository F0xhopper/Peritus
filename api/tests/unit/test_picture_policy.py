"""The picture policy: what may be shown beside an expert, and what may not.

These are the rules the plan calls decisions rather than taste — a free licence,
no marks, no living people, real image bytes — so they are asserted here on the
shapes Wikimedia actually returns rather than on a paraphrase of them.
"""

import pytest

from peritus.experts.picture import (
    Candidate,
    dimensions,
    is_free_license,
    is_living_human,
    is_on_topic,
    looks_like_a_mark,
    rank,
    sniff,
    strip_html,
)


def _extmeta(**fields) -> dict:
    """Wikimedia wraps every field as ``{"value": ..., "source": ...}``."""
    return {k: {"value": v, "source": "commons-desc-page"} for k, v in fields.items()}


# ── licences ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "short_name",
    [
        "Public domain",
        "public domain",
        "PD-US",
        "PD-old-100",
        "CC0",
        "CC BY 4.0",
        "CC BY-SA 3.0",
        "cc-by-sa-4.0",
    ],
)
def test_accepts_every_free_licence(short_name):
    assert is_free_license(_extmeta(LicenseShortName=short_name)) is True


@pytest.mark.parametrize(
    "short_name",
    [
        "CC BY-NC 4.0",
        "CC BY-NC-SA 3.0",
        "CC BY-ND 4.0",
        "Fair use",
        "Non-free logo",
        "GFDL",              # copyleft, but not one we have cleared
        "",
    ],
)
def test_refuses_everything_else(short_name):
    assert is_free_license(_extmeta(LicenseShortName=short_name)) is False


def test_an_unlabelled_file_is_not_a_free_file():
    """Fail closed: no LicenseShortName at all is a refusal, not a shrug."""
    assert is_free_license({}) is False
    assert is_free_license(_extmeta(Artist="Someone")) is False
    assert is_free_license(None) is False  # type: ignore[arg-type]


def test_a_restriction_refuses_an_otherwise_free_file():
    """Commons flags trademarks and personality rights separately from copyright.

    A logo can be PD-textlogo *and* trademarked; a photo of a person can be CC
    BY *and* carry personality rights. Either makes it wrong beside an expert.
    """
    free = _extmeta(LicenseShortName="Public domain")
    assert is_free_license(free) is True
    assert is_free_license({**free, **_extmeta(Restrictions="trademarked")}) is False
    assert is_free_license({**free, **_extmeta(Restrictions="personality")}) is False
    # An empty Restrictions field is the normal case and must not refuse.
    assert is_free_license({**free, **_extmeta(Restrictions="")}) is True


# ── marks ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "file_name",
    [
        "Flag_of_Japan.svg",
        "Flag of France.png",
        "Map_of_Greece.jpg",
        "Google_logo.png",
        "Seal_of_the_President.png",
        "Coat_of_arms_of_Spain.png",
        "Coat of arms of Spain.png",
        "Emblem_of_the_UN.png",
        "Signature_of_Einstein.png",
        "Belgium_locator_map.png",
        "Stoicism_banner.jpg",
        "Feynman_diagram.svg",   # every SVG, whatever it depicts
    ],
)
def test_marks_are_not_pictures(file_name):
    assert looks_like_a_mark(file_name) is True


@pytest.mark.parametrize(
    "file_name",
    [
        "Zeno_of_Citium_Pushkin.jpg",
        "Gentile_da_Fabriano_052.jpg",
        "Varroa_destructor_on_honeybee_host.jpg",
        "Marcus_Aurelius_Metropolitan_Museum.jpg",
    ],
)
def test_real_pictures_survive(file_name):
    assert looks_like_a_mark(file_name) is False


def test_an_empty_file_name_is_treated_as_a_mark():
    """Nothing to judge means nothing we will ship. Fail closed."""
    assert looks_like_a_mark("") is True


# ── living people ───────────────────────────────────────────────────────────


def _claims(*, human: bool, died: bool) -> dict:
    claims: dict = {}
    if human:
        claims["P31"] = [
            {"mainsnak": {"datavalue": {"value": {"id": "Q5", "entity-type": "item"}}}}
        ]
    if died:
        claims["P570"] = [{"mainsnak": {"datavalue": {"value": {"time": "+1650-02-11"}}}}]
    return claims


def test_a_living_person_is_refused():
    assert is_living_human(_claims(human=True, died=False)) is True


def test_a_dead_person_is_fine():
    """Historical figures are the best picture available for most topics."""
    assert is_living_human(_claims(human=True, died=True)) is False


def test_a_non_human_subject_is_fine():
    """A species, a concept or a building is never a publicity-rights problem."""
    honeybee = {
        "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q16521"}}}}]
    }
    assert is_living_human(honeybee) is False


def test_an_unclassified_article_is_judged_on_its_other_rules():
    """No Wikidata item, no claims, or unreadable claims — not a refusal.

    Refusing everything Wikidata has not catalogued would throw away exactly the
    abstract topics that most need a picture.
    """
    assert is_living_human({}) is False
    assert is_living_human(None) is False  # type: ignore[arg-type]
    assert is_living_human({"P31": [{}]}) is False


# ── ranking ─────────────────────────────────────────────────────────────────


def _candidate(title: str, rank_: int, mime: str = "image/jpeg", w: int = 800) -> Candidate:
    return Candidate(
        page_title=title,
        page_url=f"https://en.wikipedia.org/wiki/{title}",
        file_name=f"File:{title}.jpg",
        thumb_url="https://upload.wikimedia.org/thumb.jpg",
        thumb_width=512,
        thumb_height=512,
        original_width=w,
        original_height=w,
        wikibase_item=None,
        query="q",
        rank=rank_,
        mime=mime,
        license="Public domain",
    )


def test_the_topics_own_article_outranks_everything():
    ordered = rank(
        [_candidate("Stoic physics", 0), _candidate("Stoicism", 5)], topic="Stoicism"
    )
    assert ordered[0].page_title == "Stoicism"


def test_the_exact_title_match_ignores_case_and_punctuation():
    ordered = rank(
        [_candidate("Other", 0), _candidate("Stoicism!", 3)], topic="  stoicism "
    )
    assert ordered[0].page_title == "Stoicism!"


def test_search_order_decides_among_equals():
    ordered = rank([_candidate("B", 3), _candidate("A", 1)], topic="Zeno")
    assert [c.page_title for c in ordered] == ["A", "B"]


def test_a_photograph_outranks_a_rendered_diagram_at_the_same_position():
    ordered = rank(
        [_candidate("A", 2, mime="image/png"), _candidate("B", 2, mime="image/jpeg")],
        topic="Zeno",
    )
    assert ordered[0].page_title == "B"


def test_ranking_is_deterministic():
    candidates = [_candidate("C", 2), _candidate("A", 0), _candidate("B", 1)]
    assert [c.page_title for c in rank(candidates, "x")] == [
        c.page_title for c in rank(list(reversed(candidates)), "x")
    ]


# ── the bytes themselves ────────────────────────────────────────────────────


def test_sniff_recognises_the_four_formats_a_browser_will_render():
    assert sniff(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff(b"GIF89a....") == "image/gif"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


def test_an_html_error_page_is_not_an_image_whatever_it_claims():
    """The content type is the server's claim; the bytes are the fact."""
    assert sniff(b"<!DOCTYPE html><html><body>404</body></html>") is None
    assert sniff(b"") is None
    assert sniff(b"RIFFxxxxNOTWEBP") is None


def test_credit_lines_arrive_as_html_and_are_stripped():
    raw = '<a href="//commons.wikimedia.org/wiki/User:Foo" title="User:Foo">Foo</a>'
    assert strip_html(raw) == "Foo"
    assert strip_html("") == ""
    assert strip_html("<b>A</b>   <i>B</i>") == "A B"


# ── is it a picture of *this* subject? ──────────────────────────────────────


class TestIsOnTopic:
    """The rule that keeps an unrelated article out of the shortlist.

    Observed on a real expert: no Wikipedia article on Aristotelian logic has a
    free lead image, so the only candidate to survive every other filter was
    Susan Sontag's *Against Interpretation* — surfaced by a concept query, and
    illustrated with its dust jacket.
    """

    def test_a_hit_from_the_topics_own_search_always_passes(self):
        # Wikipedia's answer to "what is this subject" has standing even when it
        # is named nothing like it — which is the Stoicism → Zeno case exactly.
        assert is_on_topic("Zeno of Citium", query="Stoicism", topic="Stoicism") is True
        assert is_on_topic("Hellenistic philosophy", "Stoicism", "Stoicism") is True

    def test_a_concept_hit_must_share_a_substantial_word(self):
        assert is_on_topic("Term logic", "syllogism", "Aristotelian logic") is True
        assert is_on_topic("Against Interpretation", "syllogism", "Aristotelian logic") is False

    def test_a_concept_hit_may_relate_to_the_concept_instead_of_the_topic(self):
        assert is_on_topic("Feature store", "feature engineering", "Production ML") is True

    def test_common_words_do_not_connect_two_unrelated_subjects(self):
        # Without a stoplist, "systems" alone would make NoSQL an illustration
        # of machine learning.
        assert is_on_topic("NoSQL database systems", "ML system design", "Machine learning") is False

    def test_short_words_do_not_connect_either(self):
        assert is_on_topic("The Old Man and the Sea", "ion channel", "Ion channels") is False

    def test_case_and_punctuation_are_irrelevant(self):
        assert is_on_topic("Beekeeping in Australia", "beekeeping!", "Beekeeping") is True


# ── the real size of the bytes ──────────────────────────────────────────────


class TestDimensions:
    """The API's numbers describe the scale requested, not the file served.

    Ask `pageimages` for a 512px thumbnail and it reports `width: 512` while
    handing back a URL for the 960px bucket. Storing the reported number puts a
    size in the record that is not true of the image beside it.
    """

    def test_reads_a_png(self):
        # 8-byte signature, then IHDR: length, type, width, height.
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (634).to_bytes(4, "big") + (291).to_bytes(4, "big")
        assert dimensions(png) == (634, 291)

    def test_reads_a_gif(self):
        gif = b"GIF89a" + (200).to_bytes(2, "little") + (100).to_bytes(2, "little")
        assert dimensions(gif) == (200, 100)

    def test_reads_a_jpeg_by_walking_to_its_frame_header(self):
        # A JFIF APP0 segment the walk must step over, then SOF0.
        jpeg = (
            b"\xff\xd8"
            + b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
            + (640).to_bytes(2, "big") + (960).to_bytes(2, "big")
            + b"\x00" * 6
        )
        # JPEG stores height before width; the helper returns (width, height).
        assert dimensions(jpeg) == (960, 640)

    def test_reads_a_lossy_webp(self):
        webp = (
            b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8 " + b"\x00" * 10
            + (300).to_bytes(2, "little") + (150).to_bytes(2, "little")
        )
        assert dimensions(webp) == (300, 150)

    def test_returns_none_rather_than_guessing_on_something_it_cannot_read(self):
        assert dimensions(b"") is None
        assert dimensions(b"<html>not an image</html>") is None
        # Truncated mid-header: no exception, no invented number.
        assert dimensions(b"\x89PNG\r\n\x1a\n\x00\x00") is None
        assert dimensions(b"\xff\xd8\xff") is None
