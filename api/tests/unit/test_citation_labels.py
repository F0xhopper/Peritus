"""Citation labels: the work, and where in it — only when the heading is one."""

from peritus.search.labels import citation_label, citation_title, section_heading

_SUMMA = "Summa Theologica, Part I (Prima Pars) — From the Complete American Edition"


def test_a_real_heading_joins_the_title():
    assert (
        citation_label(_SUMMA, {"section": "THE EXISTENCE OF GOD"})
        == "Summa Theologica, Part I (Prima Pars) — The Existence of God"
    )


def test_a_numbered_locus_leads():
    meta = {"section": "THE EXISTENCE OF GOD", "locus": "I, q. 2, a. 3"}
    assert citation_label(_SUMMA, meta).endswith("— I, q. 2, a. 3 · The Existence of God")


def test_site_chrome_is_taken_off_the_title():
    assert citation_title("PDFAQUINAS ON DIVINE SIMPLICITY - Archive.org") == (
        "Aquinas on Divine Simplicity"
    )
    assert citation_title("(PDF) Anglo-Saxon immigration and ethnogenesis.") == (
        "Anglo-Saxon immigration and ethnogenesis."
    )
    assert citation_title("Categories (Aristotle) - Wikipedia") == "Categories (Aristotle)"


def test_what_the_chunker_took_for_a_heading_and_is_not_one():
    for raw in (
        "",
        "Full Text",
        "part of the army that belonged thereto submitted to her.  And the",
        "## Cited by (32)",
        "99. King, P D 1972, Law and Society in the Visigothic Kingdom, Cambridge.",
        "XIII",
        "99.",
        "# Save article to Kindle",
        "Cookie Preference Center",
    ):
        assert section_heading(raw) is None, raw


def test_headings_are_tidied():
    assert section_heading("CHAPTER  XIII  25") == "Chapter XIII"
    assert section_heading("## INTRODUCTION[13]") == "Introduction"
    long = "Part 1 The kinds of question we ask are as many as the kinds of things we know."
    assert section_heading(long) == "Part 1"
    # A heading the title already says is not a place in the work.
    assert (
        section_heading(
            "THE ECCLESIASTICAL HISTORY OF", "The Ecclesiastical History of the English"
        )
        is None
    )
