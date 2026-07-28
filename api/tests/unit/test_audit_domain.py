"""The published classification rules behind the audit surface.

These are the rules a researcher is told about in ``docs/audit-api.md`` and may
have to defend, so they are pinned here rather than left to whatever the code
happens to do.
"""

import pytest

from peritus.audit.domain import (
    CoverageStrength,
    classify_coverage,
    decode_json_field,
    parse_discovery_method,
    safe_mean,
)

# ── discovery provenance ──

@pytest.mark.parametrize(
    "value,expected",
    [
        ("plan", ("plan", None)),
        ("snowball", ("snowball", None)),
        ("gapfill:Stoic cosmopolitanism", ("gapfill", "Stoic cosmopolitanism")),
        ("gapfill: spaced concept ", ("gapfill", "spaced concept")),
        # A concept containing a colon keeps everything after the first one.
        ("gapfill:ethics: the basics", ("gapfill", "ethics: the basics")),
        ("gapfill:", ("gapfill", None)),
    ],
)
def test_parse_discovery_method(value, expected):
    assert parse_discovery_method(value) == expected


def test_missing_discovery_is_unknown_not_plan():
    """Sources predating migration 012 have no provenance at all.

    Folding them into 'plan' would invent a search that may never have run —
    the single most tempting and most damaging shortcut on this surface.
    """
    assert parse_discovery_method(None) == ("unknown", None)
    assert parse_discovery_method("") == ("unknown", None)


# ── coverage strength ──

def test_no_sources_is_absent_not_thin():
    """'Nothing on this concept' and 'a little on this concept' demand
    different actions, so they are different classifications."""
    assert classify_coverage(0, None, 0) is CoverageStrength.ABSENT


def test_single_source_is_thin_however_good():
    assert classify_coverage(1, 10.0, 1) is CoverageStrength.THIN


def test_low_mean_quality_demotes_to_thin():
    assert classify_coverage(6, 5.9, 4) is CoverageStrength.THIN


def test_strong_requires_count_quality_and_type_diversity():
    assert classify_coverage(4, 7.0, 2) is CoverageStrength.STRONG
    # One short on each axis in turn.
    assert classify_coverage(3, 9.0, 3) is CoverageStrength.ADEQUATE
    assert classify_coverage(9, 6.9, 5) is CoverageStrength.ADEQUATE
    assert classify_coverage(9, 9.0, 1) is CoverageStrength.ADEQUATE


def test_unscored_sources_skip_the_quality_gates():
    """Sources predating score persistence must not be treated as zero-quality."""
    assert classify_coverage(5, None, 3) is CoverageStrength.STRONG
    assert classify_coverage(2, None, 1) is CoverageStrength.ADEQUATE


# ── jsonb decoding ──

def test_decode_json_field_handles_str_and_native():
    assert decode_json_field('["a","b"]', []) == ["a", "b"]
    assert decode_json_field(["a"], []) == ["a"]
    assert decode_json_field(None, []) == []
    assert decode_json_field("not json", []) == []


def test_safe_mean_of_empty_is_none_not_zero():
    assert safe_mean([]) is None
    assert safe_mean([5.0, 8.0]) == 6.5
