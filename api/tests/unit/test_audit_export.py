"""CSV and RIS export of the screening ledger.

The export is how a grey-literature source Peritus found reaches Covidence,
Zotero or EndNote, so the properties that matter are: rejected sources travel
too, with their reason; search provenance survives the trip; and nothing in a
title can execute in a spreadsheet.
"""

import csv
import io
from datetime import UTC, datetime

from peritus.audit.export import (
    CSV_COLUMNS,
    export_filename,
    source_to_ris,
    sources_to_csv,
    sources_to_ris,
)

CREATED = datetime(2026, 7, 1, 9, 30, tzinfo=UTC)


def _accepted(**overrides) -> dict:
    row = {
        "id": 41,
        "passed": True,
        "title": "Grey literature in evidence synthesis",
        "author": "A. Reviewer, B. Second",
        "url": "https://example.org/report.pdf",
        "source_type": "pdf",
        "content_type": "paper",
        "difficulty": 4,
        "quality_score": 8.5,
        "relevance_score": 9.0,
        "drop_reason": None,
        "validator_model": "claude-haiku-4-5-20251001",
        "rubric_version": "v3-concepts-q5r6",
        "discovered_via": "gapfill:publication bias",
        "covered_concepts": '["publication bias", "search strategy"]',
        "key_claims": '["Grey literature reduces publication bias"]',
        "chunk_count": 12,
        "created_at": CREATED,
    }
    row.update(overrides)
    return row


def _rejected(**overrides) -> dict:
    return _accepted(
        id=42,
        passed=False,
        title="A blog post about reviews",
        source_type="web",
        quality_score=3.0,
        relevance_score=4.0,
        drop_reason="thin content, no methodology",
        covered_concepts=None,
        key_claims=None,
        discovered_via="plan",
        chunk_count=0,
        **overrides,
    )


def _read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


# ── CSV ──

def test_csv_carries_both_decisions_with_provenance():
    rows = _read_csv(sources_to_csv([_accepted(), _rejected()]))
    assert [r["decision"] for r in rows] == ["accepted", "rejected"]

    accepted, rejected = rows
    assert accepted["discovered_via"] == "gapfill:publication bias"
    assert accepted["discovery_method"] == "gapfill"
    assert accepted["gap_filled_for_concept"] == "publication bias"
    assert accepted["covered_concepts"] == "publication bias; search strategy"
    assert accepted["validator_model"] == "claude-haiku-4-5-20251001"
    assert accepted["rubric_version"] == "v3-concepts-q5r6"

    # The rejected half is the differentiating half — it must carry its reason.
    assert rejected["drop_reason"] == "thin content, no methodology"
    assert rejected["quality_score"] == "3.0"


def test_csv_never_puts_a_stale_reason_on_an_accepted_row():
    rows = _read_csv(sources_to_csv([_accepted(drop_reason="left over")]))
    assert rows[0]["drop_reason"] == ""


def test_csv_header_is_the_declared_column_set():
    reader = csv.reader(io.StringIO(sources_to_csv([])))
    assert tuple(next(reader)) == CSV_COLUMNS


def test_csv_defuses_spreadsheet_formulas_in_titles():
    """Titles come from arbitrary web pages; one starting with '=' would run
    on open in Excel or Sheets."""
    rows = _read_csv(sources_to_csv([_accepted(title='=HYPERLINK("http://evil","x")')]))
    assert rows[0]["title"].startswith("'=HYPERLINK")


def test_csv_flattens_newlines_out_of_values():
    rows = _read_csv(sources_to_csv([_accepted(title="Line one\nline two")]))
    assert rows[0]["title"] == "Line one line two"


def test_csv_handles_legacy_rows_with_no_provenance():
    """Sources predating migrations 009/012 export as blanks, not as 'plan'."""
    rows = _read_csv(
        sources_to_csv(
            [_accepted(discovered_via=None, validator_model=None, rubric_version=None)]
        )
    )
    assert rows[0]["discovered_via"] == ""
    assert rows[0]["discovery_method"] == "unknown"
    assert rows[0]["validator_model"] == ""


# ── RIS ──

def test_ris_record_is_well_formed():
    record = source_to_ris(_accepted())
    lines = record.split("\r\n")
    assert lines[0] == "TY  - RPRT"          # pdf → report, the grey-lit shape
    assert lines[-1] == "ER  -"              # mandatory terminator
    assert "TI  - Grey literature in evidence synthesis" in lines
    assert "UR  - https://example.org/report.pdf" in lines
    assert "PY  - 2026" in lines


def test_ris_splits_authors_onto_one_line_each():
    lines = source_to_ris(_accepted()).split("\r\n")
    assert "AU  - A. Reviewer" in lines
    assert "AU  - B. Second" in lines


def test_ris_keywords_carry_the_covered_concepts():
    lines = source_to_ris(_accepted()).split("\r\n")
    assert "KW  - publication bias" in lines
    assert "KW  - search strategy" in lines


def test_ris_note_carries_the_screening_record():
    note = next(
        line for line in source_to_ris(_rejected()).split("\r\n") if line.startswith("N1")
    )
    assert "Peritus screening decision: rejected" in note
    assert "Exclusion reason: thin content, no methodology" in note
    assert "Rubric version: v3-concepts-q5r6" in note
    assert "Discovered via: plan" in note
    # The honesty constraint travels with the record into the reviewer's tool.
    assert "not a substitute for independent human review" in note


def test_ris_note_names_the_concept_a_gapfill_search_was_run_for():
    note = next(
        line for line in source_to_ris(_accepted()).split("\r\n") if line.startswith("N1")
    )
    assert "Gap-filled for concept: publication bias" in note


def test_ris_type_mapping_covers_every_shape_of_grey_literature():
    def ty(source_type: str) -> str:
        return source_to_ris(_accepted(source_type=source_type)).split("\r\n")[0]

    assert ty("arxiv") == "TY  - UNPB"
    assert ty("gutenberg") == "TY  - BOOK"
    assert ty("youtube") == "TY  - VIDEO"
    assert ty("web") == "TY  - ELEC"
    assert ty("something_new") == "TY  - ELEC"


def test_ris_document_separates_and_terminates_records():
    doc = sources_to_ris([_accepted(), _rejected()])
    assert doc.count("ER  -") == 2
    assert doc.count("TY  - ") == 2
    assert doc.endswith("\r\n")
    assert "\n\n\n" not in doc


def test_ris_of_nothing_is_empty_not_malformed():
    assert sources_to_ris([]) == ""


def test_ris_never_emits_an_embedded_newline():
    """A raw newline inside a value silently truncates the record on import."""
    body = sources_to_ris([_accepted(title="Broken\ntitle", author="X\nY")])
    for line in body.split("\r\n"):
        # Every non-empty line must be a tag line: two letters, two spaces, a
        # hyphen. A wrapped value would break that and lose the rest of the field.
        assert line == "" or line.startswith(("ER  -", line[:2] + "  - "))
    assert "TI  - Broken title" in body


def test_export_filename_is_safe_and_descriptive():
    name = export_filename("stoic/../philosophy", "rejected", "ris")
    assert "/" not in name and ".." not in name.replace(".ris", "")
    assert name.startswith("peritus-stoic")
    assert "rejected" in name
    assert name.endswith(".ris")
