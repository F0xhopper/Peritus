"""Billing/metering configuration.

These read the environment directly rather than living in ``core/config.py``
because that file is owned elsewhere. They follow the same conventions
(``os.getenv`` with a default, resolved at import) so they can be folded into
``Settings`` verbatim later — see docs/catalog-and-credits.md for the list of
variables a deployment can set.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class BillingSettings:
    # ── Entitlements ─────────────────────────────────────────────────────────
    # Credits granted once, automatically, when an account is first provisioned.
    # The default of 1 buys exactly one Lite build: enough to see the pipeline
    # produce something of your own, not enough to be worth farming accounts.
    # Set to 0 to make builds strictly invite/grant-only.
    FREE_SIGNUP_CREDITS: int = _int("PERITUS_FREE_SIGNUP_CREDITS", 1)

    # Master switch. When false, credits are still recorded but never block a
    # build — useful while seeding the catalog, and for single-tenant installs.
    CREDITS_ENFORCED: bool = os.getenv("PERITUS_CREDITS_ENFORCED", "true").lower() == "true"

    # ── Spend caps ───────────────────────────────────────────────────────────
    # Per-build ceilings, overriding the tier defaults in experts/domain.py.
    TIER_CAP_LITE_USD: float = _float("PERITUS_TIER_CAP_LITE_USD", 0.0)
    TIER_CAP_STANDARD_USD: float = _float("PERITUS_TIER_CAP_STANDARD_USD", 0.0)
    TIER_CAP_PRO_USD: float = _float("PERITUS_TIER_CAP_PRO_USD", 0.0)

    # Enforce the cap by aborting the build. When false the cap is still
    # recorded (cap_exceeded_at) and logged, but the build runs to completion —
    # the "observe first, enforce later" setting for a new deployment.
    SPEND_CAP_ENFORCED: bool = os.getenv("PERITUS_SPEND_CAP_ENFORCED", "true").lower() == "true"

    # ── Metering ─────────────────────────────────────────────────────────────
    # How often the in-memory meter flushes aggregated usage to Postgres.
    # Also the cap-check cadence (the worker heartbeat checks on every beat).
    METER_FLUSH_INTERVAL: float = _float("PERITUS_METER_FLUSH_INTERVAL", 20.0)

    # ── Provider prices, USD per 1M tokens ───────────────────────────────────
    # Overridable so a price change does not require a deploy of new code.
    # Defaults are Anthropic first-party list prices and OpenAI embedding list
    # price as of 2026-07.
    PRICE_OVERRIDES: str = os.getenv("PERITUS_MODEL_PRICES", "")


settings = BillingSettings()
