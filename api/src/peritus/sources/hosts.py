"""Hosts whose pages are *about* a work or a person, never the work or the person's own writing.

Three places need the same list and used to disagree about it:

- triage's must-have boost, which lifted "De Ente et Essentia — Philopedia" to
  a 9 because its title named the work (docs/plans/syllabus.md, 0.B);
- the thought-leaders channel, whose best neural match for "Jacques Maritain
  Thomism" is the Stanford Encyclopedia's entry on Maritain (3.C);
- the validator's author rule, which the channel's hits are then judged by.

An encyclopedia entry is a good source *about* a subject — the plan fetchers
still search these hosts, and triage still boosts the scholarly ones. What this
list says is narrower: a page on one of these hosts is never the work a plan
named, and never a figure speaking in their own voice.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Reference works: entries that survey a subject or a person.
ENCYCLOPEDIA_HOSTS: tuple[str, ...] = (
    "plato.stanford.edu",
    "iep.utm.edu",
    "wikipedia.org",
    "britannica.com",
    "encyclopedia.com",
    "newworldencyclopedia.org",
    "philopedia.org",
    "rep.routledge.com",
    "oxfordbibliographies.com",
    "handwiki.org",
)

# Summary, study-guide and review services. Also penalised by triage's domain
# prior (sources/triage.py, _HOST_ADJUSTMENTS); a test keeps the two in step.
SUMMARY_SERVICE_HOSTS: tuple[str, ...] = (
    "goodreads.com",
    "sparknotes.com",
    "cliffsnotes.com",
    "shmoop.com",
    "gradesaver.com",
    "bookrags.com",
    "supersummary.com",
    "litcharts.com",
    "enotes.com",
    "blinkist.com",
    "getabstract.com",
    "fourminutebooks.com",
    "philosophystudent.org",
    "studyguides.com",
)

# Domains only, so the list can go straight to a search API's exclusion filter.
ABOUT_HOSTS: tuple[str, ...] = ENCYCLOPEDIA_HOSTS + SUMMARY_SERVICE_HOSTS

# About-pages that live under a path on a host that also serves primary texts:
# New Advent carries the Summa *and* the Catholic Encyclopedia. Matched on
# host + path, never handed to a domain filter.
ABOUT_PATHS: tuple[str, ...] = ("newadvent.org/cathen",)

# The names those sites put in a page title's suffix: "Thomism | Britannica",
# "Jacques Maritain (Stanford Encyclopedia of Philosophy)".
_ABOUT_SITE_NAMES = re.compile(
    r"\b(?:stanford encyclopedia|internet encyclopedia|encyclopedia|encyclopaedia|"
    r"wikipedia|britannica|philopedia|catholic encyclopedia|new advent|"
    r"sparknotes|cliffsnotes|litcharts|gradesaver|goodreads|shmoop|enotes|"
    r"supersummary|bookrags|study guide|summary|oxford bibliographies)\b",
    re.IGNORECASE,
)
# A title's site suffix: after " | ", " — ", " – " or " - ", or in trailing brackets.
_SUFFIX = re.compile(r"(?:\s[|—–-]\s(?P<tail>[^|—–]+)$)|(?:\((?P<paren>[^()]+)\)\s*$)")


def url_is_about_host(url: str) -> bool:
    """Whether a URL is on a host (or host path) whose pages are about their subject."""
    try:
        parts = urlsplit(url if "//" in (url or "") else f"//{url or ''}")
    except ValueError:
        return False
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    if any(host == h or host.endswith(f".{h}") for h in ABOUT_HOSTS):
        return True
    target = f"{host}{(parts.path or '').lower()}"
    return any(target.startswith(p) for p in ABOUT_PATHS)


def title_names_about_site(title: str) -> bool:
    """Whether a page title ends with the name of an encyclopedia or summary service."""
    match = _SUFFIX.search(title or "")
    if match is None:
        return False
    tail = match.group("tail") or match.group("paren") or ""
    return bool(_ABOUT_SITE_NAMES.search(tail))
