"""Substance: how much of a work a fetched source's text actually is.

Quality and tier describe what a source *is*. Neither says whether the pipeline
got the thing itself or a paragraph about it, and the difference decided the
Thomism corpus (job 53): twelve of its 43 accepted sources were catalogue
records — a Library of Congress table of contents, CiNii entries, Choice
reviews — passed at q8/r9 as *secondary* on 300–4,500 characters of text.

``full``     the text is the work, as far as the fetcher can tell;
``partial``  a landing page, or a text cut to the fetcher's length cap;
``abstract`` the fetcher could only get an abstract, or under a stub's length.

An ``abstract`` source still ships — a good abstract is one retrievable
paragraph and a citation the RIS export wants — but it never counts toward
coverage, so it can never be the reason the loop stops looking.
"""

from __future__ import annotations

from peritus.sources.domain import RawSource

SUBSTANCE_FULL = "full"
SUBSTANCE_PARTIAL = "partial"
SUBSTANCE_ABSTRACT = "abstract"

# Under this, whatever the fetch method said, the text is a stub.
STUB_CHARS = 1_500

_PARTIAL_METHODS = frozenset({"oa_landing_html"})


def substance_of(raw: RawSource) -> str:
    method = raw.metadata.get("full_text_method")
    if method == "abstract" or len(raw.text) < STUB_CHARS:
        return SUBSTANCE_ABSTRACT
    if method in _PARTIAL_METHODS or raw.metadata.get("truncated"):
        return SUBSTANCE_PARTIAL
    return SUBSTANCE_FULL


def abstract_chars(raw: RawSource) -> int:
    """Length of the abstract an abstract-only source rests on.

    The fetchers write ``title\\n\\nabstract`` as the text and keep the abstract
    in metadata; the metadata copy is the honest measure.
    """
    abstract = raw.metadata.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return len(abstract.strip())
    return len(raw.text)
