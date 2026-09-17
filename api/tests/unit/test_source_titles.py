"""The title a reader actually sees.

Titles arrive from eleven fetchers and are stored as given; these are the three
things that came with them, and the rule that nothing else is touched.
"""

from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.titles import clean_title


def test_entities_and_tags_are_resolved():
    assert (
        clean_title("The symbiotic bacteria &lt;i&gt;Frischella perrara&lt;/i&gt; genome")
        == "The symbiotic bacteria Frischella perrara genome"
    )
    assert clean_title("Bees <sub>and</sub> wasps") == "Bees and wasps"
    assert clean_title("Apis &amp; Varroa") == "Apis & Varroa"


def test_a_shouted_title_is_title_cased_with_small_words_kept_low():
    assert (
        clean_title("LANGSTROTH ON THE HIVE AND THE HONEY-BEE")
        == "Langstroth on the Hive and the Honey-Bee"
    )


def test_a_mixed_case_title_with_acronyms_is_left_alone():
    # The rule is "every letter is a capital", not "most are" — lowering the
    # acronyms in a normal title would be a worse error than the shouting.
    for title in (
        "The ABC and XYZ of Bee Culture",
        "A Virulent Strain of Deformed Wing Virus (DWV) of Honeybees",
    ):
        assert clean_title(title) == title


def test_short_capitalised_strings_are_acronyms_not_shouting():
    assert clean_title("DWV") == "DWV"
    assert clean_title("PNAS 2019") == "PNAS 2019"


def test_whitespace_is_collapsed_and_nothing_is_dropped():
    assert clean_title("  spaced\n  out  title ") == "spaced out title"
    assert clean_title(None) == ""
    assert clean_title("") == ""


def test_every_source_is_cleaned_where_it_enters():
    candidate = SourceCandidate(
        source_type=SourceType.WEB,
        url="https://example.org/a",
        title="Bees &amp; <i>Varroa</i>",
        author=None,
        snippet="",
    )
    assert candidate.title == "Bees & Varroa"

    raw = RawSource(
        source_type=SourceType.WEB,
        url="https://example.org/a",
        title="THE HIVE AND THE HONEY BEE",
        author=None,
        text="",
    )
    assert raw.title == "The Hive and the Honey Bee"
