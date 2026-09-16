"""Whether a fetched text is in the corpus's language, without a model call.

The validator scores what it is shown, and it will score a Spanish paper on
Gilson and Dewan as relevant to Thomism — which it is — for an expert that
answers in English from passages it cannot quote. The check is the share of
common function words in a sample of the text: English prose runs at 35–50%,
Romance and Germanic languages share only a handful of short words with it and
fall well under 10%. Only English has a word list; for any other configured
language the check passes everything.
"""

from __future__ import annotations

import re

from peritus.core.config import settings

# Function words that are frequent in English and rare or absent in the other
# languages a web search returns. "a", "in", "no", "me" are left out: they are
# words in Spanish, Italian, German or Latin too.
_ENGLISH = frozenset(
    {
        "the",
        "of",
        "and",
        "to",
        "is",
        "that",
        "it",
        "for",
        "was",
        "with",
        "as",
        "on",
        "be",
        "by",
        "this",
        "are",
        "from",
        "or",
        "at",
        "which",
        "not",
        "have",
        "but",
        "his",
        "they",
        "has",
        "an",
        "their",
        "were",
        "been",
        "one",
        "all",
        "we",
        "there",
        "would",
        "can",
        "what",
        "its",
        "when",
        "who",
        "more",
        "will",
        "these",
        "than",
        "into",
        "so",
        "if",
        "also",
        "only",
        "other",
        "some",
        "such",
        "them",
        "should",
        "he",
        "she",
        "you",
        "your",
        "our",
        "those",
        "then",
        "may",
        "how",
    }
)
_WORD = re.compile(r"[A-Za-zÀ-ÿ']+")
_SAMPLE_CHARS = 6_000
_MIN_WORDS = 80
_MIN_SHARE = 0.15


def english_share(text: str) -> float | None:
    """Share of English function words in a sample from the text's middle."""
    middle = len(text) // 2
    sample = text[max(0, middle - _SAMPLE_CHARS // 2) : middle + _SAMPLE_CHARS // 2]
    words = [w.casefold() for w in _WORD.findall(sample)]
    if len(words) < _MIN_WORDS:
        return None
    return sum(1 for w in words if w in _ENGLISH) / len(words)


def is_expected_language(text: str) -> bool:
    """False only when the text is confidently not in the corpus language."""
    if settings.CORPUS_LANGUAGE != "en":
        return True
    share = english_share(text)
    return share is None or share >= _MIN_SHARE
