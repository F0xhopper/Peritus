"""Entity resolution rules — which graph nodes are the same thing.

Embedding cosine alone merged too little. The beekeeping expert kept "Varroa
destructor", "Varroa destructor mite", "Varroa destructor mites", "Varroa mite"
and "Varroa mites" as separate concepts, and "Deformed Wing Virus (DWV)" apart
from "DWV (Deformed Wing Virus)": inflection, a parenthetical acronym, or a
different description sentence was enough to fall under 0.93. The cost
compounds — `about` groups fragment across the spellings, so a concept three
sources discuss can fail reconciliation's two-source rule, and a passage's
"About:" line names one concept four times.

So resolution runs in two steps. First a deterministic one: concepts whose
canonical labels are equal (or where one's acronym is the other's label) are
merged outright. Then the embedding pass, at a lower threshold for concepts
that share a head noun than for anything else. Pure functions; the builder
does the database work.
"""

import re

#: Cosine threshold for two nodes of the same type.
RESOLVE_THRESHOLD = 0.93
#: …lowered for two concepts whose canonical labels end in the same head noun,
#: where the remaining difference is usually a modifier ("Varroa mite" /
#: "Varroa destructor mite") rather than a different thing.
RESOLVE_THRESHOLD_SAME_HEAD = 0.90

_ARTICLES = ("the ", "a ", "an ")
_TRAILING_PAREN = re.compile(r"^(?P<head>.+?)\s*\((?P<paren>[^()]+)\)\s*$")
# Two or more capitals, short, one token: DWV, mRNA, COVID-19. Not "Summa".
_ACRONYM = re.compile(r"^(?=(?:[^A-Z]*[A-Z]){2})[A-Za-z0-9&-]{2,8}$")
# Words whose trailing "s" is not a plural.
_NOT_PLURAL = ("ss", "us", "is", "ics", "ous", "sis")


def canonical_label(label: str) -> tuple[str, str | None]:
    """``(canonical, alias)`` for a concept label.

    Casefolded, punctuation-flattened, leading article dropped, head noun
    singularised. A parenthetical that is an acronym of the rest becomes the
    alias ("Deformed Wing Virus (DWV)" → "deformed wing virus", "dwv"); one
    that is the expansion of an acronym head swaps round ("DWV (Deformed Wing
    Virus)" → the same pair).
    """
    text = " ".join(label.replace("—", " ").replace("–", " ").split()).strip(" .,;:")
    alias: str | None = None
    m = _TRAILING_PAREN.match(text)
    if m:
        head, paren = m.group("head").strip(), m.group("paren").strip()
        if _abbreviates(paren, head):
            text, alias = head, paren
        elif _abbreviates(head, paren):
            text, alias = paren, head
    canonical = _normalise(text)
    return canonical, (_normalise(alias) if alias else None)


def _abbreviates(acronym: str, phrase: str) -> bool:
    """Whether ``acronym`` plausibly stands for ``phrase``.

    It must look like an acronym, the phrase must not, and they must start with
    the same letter. The last is what keeps a qualifier in brackets from being
    read as an alias: measured on production labels, "Vision Domain Evaluation
    (CIFAR10)" and "… (MNIST)" otherwise merged as one concept.
    """
    if not _ACRONYM.match(acronym) or _ACRONYM.match(phrase):
        return False
    return acronym[:1].casefold() == phrase.lstrip()[:1].casefold()


def head_noun(canonical: str) -> str:
    return canonical.rsplit(" ", 1)[-1] if canonical else ""


def _normalise(text: str) -> str:
    text = re.sub(r"[-_/]", " ", text.casefold())
    text = re.sub(r"[^\w\s&']", "", text)
    text = " ".join(text.split())
    for article in _ARTICLES:
        if text.startswith(article) and len(text) > len(article):
            text = text[len(article) :]
            break
    words = text.split(" ")
    words[-1] = _singular(words[-1])
    return " ".join(words)


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith(_NOT_PLURAL):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def canonical_merge_plan(nodes: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Groups of concept nodes that are the same concept by label alone.

    Returns ``(keep, [drop, …])`` per group of two or more. The node kept is
    the best evidenced (most chunks), so the surviving label is the spelling
    the corpus used most. Claims are not canonicalised: a claim is a sentence,
    and two sentences that differ by a plural can say different things.
    """
    concepts = [n for n in nodes if (n.get("node_type") or "concept") == "concept"]
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        while parent.setdefault(key, key) != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys: dict[int, str] = {}
    for node in concepts:
        canonical, alias = canonical_label(node.get("label") or "")
        if not canonical:
            continue
        keys[node["id"]] = canonical
        find(canonical)
        if alias:
            union(canonical, alias)

    groups: dict[str, list[dict]] = {}
    for node in concepts:
        key = keys.get(node["id"])
        if key is not None:
            groups.setdefault(find(key), []).append(node)

    plan: list[tuple[dict, list[dict]]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda n: (-len(n.get("chunk_ids") or []), n["id"]))
        plan.append((ranked[0], ranked[1:]))
    return plan


def pair_threshold(a: dict, b: dict) -> float | None:
    """The cosine two nodes must reach to merge, or None if they never may."""
    type_a = a.get("node_type") or "concept"
    if type_a != (b.get("node_type") or "concept"):
        # A claim is never the same node as a concept, however close the text.
        return None
    if type_a == "concept":
        head_a = head_noun(canonical_label(a.get("label") or "")[0])
        if head_a and head_a == head_noun(canonical_label(b.get("label") or "")[0]):
            return RESOLVE_THRESHOLD_SAME_HEAD
    return RESOLVE_THRESHOLD
