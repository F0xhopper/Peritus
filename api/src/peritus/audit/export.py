"""CSV and RIS serialisation of the screening ledger.

Why RIS specifically: a grey-literature source found by Peritus is invisible to
the rest of a reviewer's toolchain until it can be imported into Covidence,
Zotero or EndNote, and RIS is what those read. Without it the ledger is a page
someone looks at; with it, the sources Peritus found join the review the user is
actually running. That makes this the integration, not a nicety.

Both formats carry the same rows: **accepted and rejected sources alike**, each
with its scores, its exclusion reason, the model and rubric version that judged
it, and — the field no bibliographic-database export has an equivalent for —
which search produced it.

Pure functions over row dicts, so the formats are testable without a database.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from peritus.audit.domain import decode_json_field, parse_discovery_method

CSV_COLUMNS: tuple[str, ...] = (
    "source_id",
    "decision",
    "title",
    "author",
    "url",
    "source_type",
    "content_type",
    "difficulty",
    "quality_score",
    "relevance_score",
    "drop_reason",
    "validator_model",
    "rubric_version",
    "discovered_via",
    "discovery_method",
    "gap_filled_for_concept",
    "covered_concepts",
    "key_claims",
    "passage_count",
    "recorded_at",
)

# RIS reference types per Peritus source type. RIS has no preprint or forum
# type, so the mapping picks the nearest type the importers understand and the
# exact origin is preserved in the notes field of every record.
RIS_TYPES: dict[str, str] = {
    "arxiv": "UNPB",   # unpublished work — preprint
    "pdf": "RPRT",     # report — the usual grey-literature shape
    "gutenberg": "BOOK",
    "youtube": "VIDEO",
    "wikipedia": "ELEC",
    "web": "ELEC",
    "exa": "ELEC",
    "reddit": "ELEC",
    "thought_leader": "ELEC",
}
RIS_DEFAULT_TYPE = "ELEC"

# RIS is a line-oriented format with CRLF terminators; importers are stricter
# about this than the spec suggests.
_RIS_EOL = "\r\n"

# Leading characters a spreadsheet treats as the start of a formula. A source
# title beginning with one of these would execute on open, so cells are
# defused. Real risk here: titles come from arbitrary web pages.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _decision(row: dict[str, Any]) -> str:
    return "accepted" if row.get("passed") else "rejected"


def _flatten(value: Any) -> str:
    """One-line string form. RIS breaks on embedded newlines; CSV survives them
    but a ledger is far easier to read and diff without them."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return " ".join(str(value).split())


def _defuse(value: str) -> str:
    """Neutralise spreadsheet formula injection in a CSV cell."""
    if value and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _joined(value: Any) -> str:
    items = decode_json_field(value, [])
    if not isinstance(items, list):
        return ""
    return "; ".join(_flatten(i) for i in items if i is not None)


def source_to_csv_row(row: dict[str, Any]) -> dict[str, str]:
    method, concept = parse_discovery_method(row.get("discovered_via"))
    values = {
        "source_id": row.get("id"),
        "decision": _decision(row),
        "title": row.get("title"),
        "author": row.get("author"),
        "url": row.get("url"),
        "source_type": row.get("source_type"),
        "content_type": row.get("content_type"),
        "difficulty": row.get("difficulty"),
        "quality_score": row.get("quality_score"),
        "relevance_score": row.get("relevance_score"),
        # Only rejected rows carry an exclusion reason; leaving a stale value on
        # an accepted row would misrepresent the decision.
        "drop_reason": row.get("drop_reason") if not row.get("passed") else None,
        "validator_model": row.get("validator_model"),
        "rubric_version": row.get("rubric_version"),
        "discovered_via": row.get("discovered_via"),
        "discovery_method": method,
        "gap_filled_for_concept": concept,
        "covered_concepts": _joined(row.get("covered_concepts")),
        "key_claims": _joined(row.get("key_claims")),
        "passage_count": row.get("chunk_count"),
        "recorded_at": row.get("created_at"),
    }
    return {k: _defuse(_flatten(v)) for k, v in values.items()}


def sources_to_csv(rows: list[dict[str, Any]]) -> str:
    """The full ledger as CSV, one row per source considered."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(source_to_csv_row(row))
    return buffer.getvalue()


def _ris_note(row: dict[str, Any]) -> str:
    """The screening record, packed into the notes field.

    Importers surface N1 as a note or an "Extra" field, so this is what a
    reviewer sees next to the reference inside Covidence or Zotero. It is
    written as labelled ``key: value`` pairs so it stays readable there and
    parseable if anyone wants to pull it apart again.
    """
    method, concept = parse_discovery_method(row.get("discovered_via"))
    parts: list[tuple[str, Any]] = [
        ("Peritus screening decision", _decision(row)),
        ("Quality score", row.get("quality_score")),
        ("Relevance score", row.get("relevance_score")),
    ]
    if not row.get("passed"):
        parts.append(("Exclusion reason", row.get("drop_reason") or "(not recorded)"))
    parts += [
        ("Validator model", row.get("validator_model")),
        ("Rubric version", row.get("rubric_version")),
        ("Discovered via", row.get("discovered_via")),
        ("Discovery method", method),
    ]
    if concept:
        parts.append(("Gap-filled for concept", concept))
    concepts = _joined(row.get("covered_concepts"))
    if concepts:
        parts.append(("Concepts covered", concepts))
    parts.append(("Peritus source type", row.get("source_type")))
    parts.append(
        (
            "Note",
            "Automated first-pass screening; not a substitute for independent "
            "human review.",
        )
    )
    return " | ".join(
        f"{label}: {_flatten(value)}" for label, value in parts if value not in (None, "")
    )


def source_to_ris(row: dict[str, Any]) -> str:
    """One RIS record. Ends with the mandatory ``ER`` terminator."""
    lines: list[tuple[str, str]] = [
        ("TY", RIS_TYPES.get(str(row.get("source_type") or ""), RIS_DEFAULT_TYPE)),
        ("ID", f"peritus-{row.get('id')}"),
        ("TI", _flatten(row.get("title"))),
    ]

    author = _flatten(row.get("author"))
    if author:
        # Multiple authors arrive comma-joined from the fetchers; RIS wants one
        # AU line each, which is how importers build an author list.
        for name in [a.strip() for a in author.split(",") if a.strip()]:
            lines.append(("AU", name))

    created = row.get("created_at")
    if isinstance(created, (datetime, date)):
        lines.append(("PY", str(created.year)))
        lines.append(("DA", created.strftime("%Y/%m/%d")))

    url = _flatten(row.get("url"))
    if url:
        lines.append(("UR", url))

    claims = _joined(row.get("key_claims"))
    if claims:
        lines.append(("AB", claims))

    concepts = decode_json_field(row.get("covered_concepts"), [])
    if isinstance(concepts, list):
        for concept in concepts:
            if concept:
                lines.append(("KW", _flatten(concept)))

    lines.append(("DP", "Peritus"))
    lines.append(("DB", f"Peritus corpus ({_flatten(row.get('source_type'))})"))
    lines.append(("N1", _ris_note(row)))
    lines.append(("ER", ""))

    return _RIS_EOL.join(f"{tag}  - {value}".rstrip() for tag, value in lines)


def sources_to_ris(rows: list[dict[str, Any]]) -> str:
    """The full ledger as RIS, importable into Covidence, Zotero and EndNote."""
    if not rows:
        return ""
    return _RIS_EOL.join(source_to_ris(row) for row in rows) + _RIS_EOL


def export_filename(slug: str, decision: str, extension: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug) or "expert"
    return f"peritus-{safe}-{decision}-ledger-{stamp}.{extension}"
