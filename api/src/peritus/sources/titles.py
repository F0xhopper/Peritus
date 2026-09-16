"""Source titles, as a reader should see them.

Titles arrive from eleven fetchers and are stored as given. Three things come
with them, and all three reach the Sources page, the citation on an answer and
the bibliography someone exports:

- **Markup.** Search APIs return the publisher's own rich text, so a title can
  read ``The symbiotic bacteria &lt;i&gt;Frischella perrara&lt;/i&gt;…`` —
  entity-escaped tags, printed literally.
- **Shouting.** Catalogue metadata is often all capitals
  (``LANGSTROTH ON THE HIVE AND THE HONEY-BEE``), which in a list of ordinary
  titles reads as emphasis nobody chose.
- **Stray whitespace**, including newlines from scraped pages.

Cleaning happens once, where a source enters the system, rather than in each of
the four places that render a title. The rules are deliberately conservative:
nothing is truncated, no words are dropped, and a title that is already
well-formed comes back unchanged.
"""

import html
import re

#: Words that stay lowercase inside a de-shouted title. Only ever applied to a
#: title that was entirely capitals, so no author's own casing is overridden.
_SMALL_WORDS = frozenset(
    (
        "a",
        "an",
        "the",
        "and",
        "or",
        "nor",
        "but",
        "for",
        "so",
        "yet",
        "at",
        "by",
        "in",
        "of",
        "on",
        "to",
        "up",
        "via",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "as",
        "if",
        "is",
        "it",
        "its",
    )
)

_TAG = re.compile(r"<[^>]{1,120}>")
_LETTERS = re.compile(r"[A-Za-z]")


def clean_title(title: str | None) -> str:
    """Unescape, de-tag, de-shout and collapse whitespace in a source title."""
    if not title:
        return ""
    # Twice: a title can arrive double-escaped (``&amp;lt;i&amp;gt;``), which is
    # what an API that escaped an already-escaped field produces.
    text = html.unescape(html.unescape(title))
    text = _TAG.sub(" ", text)
    text = " ".join(text.split())
    return _deshout(text)


def _deshout(text: str) -> str:
    """Title-case a title that is all capitals; leave every other title alone.

    The threshold is "every letter is a capital", not "most are": a title like
    ``The ABC and XYZ of Bee Culture`` is mixed case with acronyms in it, and
    lowering those would be an error rather than a fix.
    """
    letters = _LETTERS.findall(text)
    # Short strings are acronyms or codes ("DWV", "PNAS"), not shouting.
    if len(letters) < 12 or any(ch.islower() for ch in letters):
        return text

    words = text.split(" ")
    out: list[str] = []
    for position, word in enumerate(words):
        lowered = word.lower()
        if position > 0 and position < len(words) - 1 and lowered.strip(",.;:") in _SMALL_WORDS:
            out.append(lowered)
        else:
            out.append(_capitalise(lowered))
    return " ".join(out)


def _capitalise(word: str) -> str:
    """Capitalise a word's first letter and every letter after a hyphen or slash."""
    return re.sub(r"(^|[-/(])([a-z])", lambda m: m.group(1) + m.group(2).upper(), word)
