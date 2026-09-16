"""Opt-in capture of everything that reaches validation, for screening evaluation.

A screening fixture cannot be rebuilt from the database. The ``sources`` table
stores scores and provenance but no text, and a source the validator dropped has
no chunks either — so the moment a build finishes, the evidence of *what the
validator was actually looking at* is gone. That makes it impossible to ask the
only question that matters about a rubric change: did it get better, or did it
just get different?

So when ``SCREENING_CAPTURE_DIR`` is set, every source is written to disk
immediately before it is judged. Off by default, because it writes whole
documents to the filesystem.

Deliberately a wrapper around the *caller* of ``validate_sources`` rather than
something inside the validator: every path that validates — round 0, a later
discovery round, a future re-screen of an existing corpus — is then captured by
construction, and the validator stays a pure scoring function.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource
from peritus.sources.validator import RUBRIC_VERSION

logger = get_logger(__name__)

MANIFEST_NAME = "manifest.json"


def capture_dir() -> Path | None:
    raw = (settings.SCREENING_CAPTURE_DIR or "").strip()
    return Path(raw).expanduser() if raw else None


def source_to_record(source: RawSource, round_n: int = 0) -> dict[str, Any]:
    """One JSONL line. Everything ``validate_sources`` will see, plus provenance."""
    return {
        "source_type": source.source_type.value,
        "url": source.url,
        "title": source.title,
        "author": source.author,
        "text": source.text,
        "metadata": _jsonable(source.metadata),
        "identifiers": source.identifiers.to_dict(),
        "discovered_via": source.metadata.get("discovered_via", "plan"),
        "full_text_method": source.metadata.get("full_text_method"),
        "round": round_n,
    }


def record_to_source(record: dict[str, Any]) -> RawSource:
    """Rebuild a ``RawSource`` from a captured line, for the screening runner."""
    from peritus.sources.domain import Identifiers, SourceType

    metadata = dict(record.get("metadata") or {})
    metadata.setdefault("discovered_via", record.get("discovered_via", "plan"))
    if record.get("full_text_method"):
        metadata.setdefault("full_text_method", record["full_text_method"])
    return RawSource(
        source_type=SourceType(record["source_type"]),
        url=record.get("url") or "",
        title=record.get("title") or "",
        author=record.get("author"),
        text=record.get("text") or "",
        metadata=metadata,
        identifiers=Identifiers.from_dict(record.get("identifiers")),
    )


def capture_for_screening(
    expert,
    job_id: int | None,
    sources: list[RawSource],
    topic: str,
    key_concepts: list[str],
    round_n: int = 0,
) -> Path | None:
    """Append this round's sources to ``<dir>/<slug>/<job_id>.jsonl``.

    Never raises: a capture is a debugging aid, and a full disk or a bad path
    must not fail a build that has already been paid for.
    """
    root = capture_dir()
    if root is None or not sources:
        return None
    try:
        target = root / str(getattr(expert, "name", "expert"))
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{job_id or 'nojob'}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for source in sources:
                handle.write(json.dumps(source_to_record(source, round_n)) + "\n")
        _write_manifest(target, expert, topic, key_concepts)
    except Exception as exc:
        logger.warning(
            "Screening capture failed (%s: %s) — build continues", type(exc).__name__, exc
        )
        return None
    logger.info("Captured %d source(s) for screening evaluation → %s", len(sources), path)
    return path


def _write_manifest(target: Path, expert, topic: str, key_concepts: list[str]) -> None:
    from peritus.core.config import settings as core_settings

    manifest = {
        "expert": getattr(expert, "name", None),
        "tier": str(getattr(expert, "tier", "")),
        "topic": topic,
        "key_concepts": key_concepts,
        "rubric_version": RUBRIC_VERSION,
        "validator_model": core_settings.FAST_MODEL,
        "review_model": core_settings.VALIDATE_REVIEW_MODEL or core_settings.CLAUDE_MODEL,
        "second_opinion_enabled": core_settings.VALIDATE_SECOND_OPINION,
    }
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    """Metadata comes from arbitrary APIs; keep only what round-trips through JSON."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(v) for v in value]
        return str(value)
