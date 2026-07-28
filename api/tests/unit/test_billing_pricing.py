"""Pricing and metering unit tests — no DB, no network."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from peritus.billing.domain import (
    FREE,
    LAB,
    STARTER,
    InsufficientCredits,
    TierNotInPlan,
    credit_cost,
    get_plan,
    spend_cap_usd,
)
from peritus.billing.metering import BuildMeter, Stage, stage_for_event
from peritus.billing.pricing import (
    BATCH_MULTIPLIER,
    embedding_cost_usd,
    message_cost_usd,
    price_for,
)
from peritus.experts.domain import ExpertTier

# ── price resolution ────────────────────────────────────────────────────────

def test_dated_snapshot_resolves_to_its_family():
    """Config uses dated ids (claude-haiku-4-5-20251001); prices are keyed by family."""
    assert price_for("claude-haiku-4-5-20251001") == price_for("claude-haiku-4-5")


def test_longest_prefix_wins():
    # "claude-opus-4-8" must not be resolved by a shorter, different entry.
    assert price_for("claude-opus-4-8").input_per_mtok == Decimal("5.00")
    assert price_for("claude-sonnet-5").input_per_mtok == Decimal("3.00")


def test_unknown_model_is_priced_conservatively():
    """An unknown model must over-estimate so it trips the cap, not slip past it."""
    unknown = price_for("some-model-we-have-never-seen")
    assert unknown.input_per_mtok >= price_for("claude-sonnet-5").input_per_mtok


# ── cost arithmetic ─────────────────────────────────────────────────────────

def test_message_cost_matches_list_price():
    # 1M input + 1M output on Haiku 4.5 = $1.00 + $5.00.
    assert message_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == Decimal("6.00")


def test_batch_mode_halves_the_cost():
    live = message_cost_usd("claude-haiku-4-5", 500_000, 100_000, batch=False)
    batched = message_cost_usd("claude-haiku-4-5", 500_000, 100_000, batch=True)
    assert batched == live * BATCH_MULTIPLIER


def test_cache_reads_are_cheaper_than_fresh_input():
    fresh = message_cost_usd("claude-haiku-4-5", 100_000, 0)
    cached = message_cost_usd("claude-haiku-4-5", 0, 0, cache_read_input_tokens=100_000)
    assert cached < fresh


def test_embeddings_bill_input_only():
    assert embedding_cost_usd("text-embedding-3-large", 1_000_000) == Decimal("0.13")


def test_observed_standard_build_lands_near_measured_cost():
    """Sanity-check against a real standard-tier build: ~$1.04 live / ~$0.54 batched.

    Contextualisation and graph extraction carry ~89% of it, both on Haiku.
    This is a guard against an order-of-magnitude pricing error, not a precise
    reproduction of one build's token mix.
    """
    # ~89% of $1.04 on Haiku, at roughly 8:1 input:output.
    live = message_cost_usd("claude-haiku-4-5", 700_000, 40_000)
    assert Decimal("0.5") < live < Decimal("1.5")
    assert message_cost_usd("claude-haiku-4-5", 700_000, 40_000, batch=True) == live / 2
    # Embeddings are a rounding error next to the Claude spend (~$0.024).
    assert embedding_cost_usd("text-embedding-3-large", 200_000) < Decimal("0.05")


def test_tier_caps_sit_above_observed_build_cost():
    """Caps are a runaway valve, not a budget: comfortably above a healthy build."""
    # A standard build measured at ~$1.04 live must not trip its own ceiling.
    assert spend_cap_usd(ExpertTier.STANDARD) >= 2.0
    caps = [spend_cap_usd(t) for t in (ExpertTier.LITE, ExpertTier.STANDARD, ExpertTier.PRO)]
    assert caps == sorted(caps), "caps must increase with tier"


# ── the price ladder ────────────────────────────────────────────────────────

def test_credit_cost_increases_with_tier():
    costs = [credit_cost(t) for t in (ExpertTier.LITE, ExpertTier.STANDARD, ExpertTier.PRO)]
    assert costs == sorted(costs) and len(set(costs)) == 3


def test_plan_multiplier_widens_the_cap():
    assert spend_cap_usd(ExpertTier.PRO, LAB) > spend_cap_usd(ExpertTier.PRO, FREE)


def test_account_override_beats_plan_and_tier():
    assert spend_cap_usd(ExpertTier.LITE, LAB, account_override_usd=42.0) == 42.0


def test_unknown_plan_falls_back_to_free():
    """A legacy or mistyped plan name must not silently grant more than free."""
    assert get_plan("enterprise-platinum") is FREE
    assert get_plan(None) is FREE
    assert get_plan("starter") is STARTER


# ── denial payloads ─────────────────────────────────────────────────────────

def test_insufficient_credits_payload_is_renderable():
    exc = InsufficientCredits(required=3, available=1, tier=ExpertTier.STANDARD, plan=FREE)
    payload = exc.to_payload()["error"]
    assert payload["code"] == "insufficient_credits"
    assert payload["required_credits"] == 3
    assert payload["available_credits"] == 1
    assert payload["tier"] == "standard"
    assert payload["remedy"]["kind"] == "request_credits"
    # The message is for humans; the client renders from the structured fields.
    assert "3 credits" in payload["message"]


def test_tier_not_in_plan_lists_the_alternatives():
    exc = TierNotInPlan(tier=ExpertTier.PRO, plan=FREE)
    payload = exc.to_payload()["error"]
    assert payload["code"] == "tier_not_in_plan"
    assert payload["allowed_tiers"] == ["lite"]


# ── the meter ───────────────────────────────────────────────────────────────

def _usage(input_tokens=0, output_tokens=0, cache_creation=0, cache_read=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def test_stage_mapping_covers_the_pipeline():
    assert stage_for_event("validate") == Stage.VALIDATION
    assert stage_for_event("chunk") == Stage.CONTEXTUALIZATION
    assert stage_for_event("graph") == Stage.GRAPH_EXTRACTION
    assert stage_for_event("resolve") == Stage.GRAPH_EXTRACTION
    assert stage_for_event("persona") == Stage.PERSONA
    # Unknown stages are recorded, not dropped — spend is never unattributed.
    assert stage_for_event("some-new-stage") == Stage.OTHER
    assert stage_for_event(None) == Stage.OTHER


def test_meter_attributes_spend_to_the_current_stage():
    meter = BuildMeter(job_id=1)
    meter.observe_event({"type": "stage", "stage": 2, "name": "validate"})
    meter.record_message("claude-haiku-4-5", _usage(1000, 100), batch=False)
    meter.observe_event({"type": "stage", "stage": 4, "name": "graph"})
    meter.record_message("claude-haiku-4-5", _usage(2000, 200), batch=True)

    stages = {key[0] for key, _ in meter.drain()}
    assert stages == {Stage.VALIDATION, Stage.GRAPH_EXTRACTION}


def test_meter_records_observed_mode_not_configuration():
    """Mode comes from which call path produced the message, never from config."""
    meter = BuildMeter(job_id=1)
    meter.record_message("claude-haiku-4-5", _usage(1000, 0), batch=True)
    meter.record_message("claude-haiku-4-5", _usage(1000, 0), batch=False)
    modes = {key[3] for key, _ in meter.drain()}
    assert modes == {"batch", "live"}


def test_meter_aggregates_repeated_calls_into_one_row():
    """A Pro build makes thousands of calls; they must not become thousands of rows."""
    meter = BuildMeter(job_id=1)
    meter.set_stage(Stage.CONTEXTUALIZATION)
    for _ in range(500):
        meter.record_message("claude-haiku-4-5", _usage(100, 10), batch=False)
    rows = meter.drain()
    assert len(rows) == 1
    (_key, bucket), = rows
    assert bucket.calls == 500
    assert bucket.input_tokens == 50_000


def test_meter_trips_the_cap_and_records_embeddings():
    meter = BuildMeter(job_id=1, cap_usd=0.10)
    assert not meter.over_cap
    meter.record_message("claude-haiku-4-5", _usage(200_000, 0), batch=False)  # $0.20
    assert meter.over_cap
    assert meter.spent_usd == pytest.approx(0.20)

    meter.record_embedding("text-embedding-3-large", 10_000)
    assert meter.embed_tokens == 10_000
    providers = {key[1] for key, _ in meter.drain()}
    assert providers == {"anthropic", "openai"}


def test_meter_without_a_cap_never_trips():
    meter = BuildMeter(job_id=1, cap_usd=None)
    meter.record_message("claude-opus-5", _usage(10_000_000, 1_000_000), batch=False)
    assert not meter.over_cap


def test_drain_hands_out_deltas_but_keeps_running_totals():
    """A flush must not reset the build's spend — the cap depends on the total."""
    meter = BuildMeter(job_id=1)
    meter.record_message("claude-haiku-4-5", _usage(1_000_000, 0), batch=False)
    assert meter.drain()
    assert not meter.drain(), "a second drain has nothing left to persist"
    assert meter.spent_usd == pytest.approx(1.0), "totals survive the flush"


def test_restore_puts_rows_back_after_a_failed_flush():
    meter = BuildMeter(job_id=1)
    meter.record_message("claude-haiku-4-5", _usage(1000, 0), batch=False)
    rows = meter.drain()
    meter.restore(rows)
    assert len(meter.drain()) == len(rows)
