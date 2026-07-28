"""Token → dollars.

Prices are USD per 1,000,000 tokens. Everything here is a pure function of the
*observed* response: the model string comes off the API response, and the mode
(live vs batch) comes from which code path produced it. Nothing reads
configuration to decide what a call cost — a build that fell back from a batch
to live calls mid-stage must be priced as what actually happened.
"""

from dataclasses import dataclass
from decimal import Decimal

from peritus.billing.settings import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)

# Message Batches run at 50% of standard token prices.
BATCH_MULTIPLIER = Decimal("0.5")
# Cache reads bill at ~10% of the base input price; 5-minute cache writes at 125%.
CACHE_READ_MULTIPLIER = Decimal("0.1")
CACHE_WRITE_MULTIPLIER = Decimal("1.25")

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


def _p(input_: str, output: str) -> ModelPrice:
    return ModelPrice(Decimal(input_), Decimal(output))


# Keyed by model-id prefix so dated snapshots resolve to their family:
# "claude-haiku-4-5-20251001" matches "claude-haiku-4-5". Longest prefix wins,
# so a more specific entry always beats a more general one.
_ANTHROPIC_PRICES: dict[str, ModelPrice] = {
    "claude-fable-5":    _p("10.00", "50.00"),
    "claude-mythos-5":   _p("10.00", "50.00"),
    "claude-opus-5":     _p("5.00", "25.00"),
    "claude-opus-4-8":   _p("5.00", "25.00"),
    "claude-opus-4-7":   _p("5.00", "25.00"),
    "claude-opus-4-6":   _p("5.00", "25.00"),
    "claude-opus-4-5":   _p("5.00", "25.00"),
    "claude-sonnet-5":   _p("3.00", "15.00"),
    "claude-sonnet-4-6": _p("3.00", "15.00"),
    "claude-sonnet-4-5": _p("3.00", "15.00"),
    "claude-haiku-4-5":  _p("1.00", "5.00"),
}

# OpenAI embedding models bill input tokens only.
_OPENAI_PRICES: dict[str, ModelPrice] = {
    "text-embedding-3-large": _p("0.13", "0"),
    "text-embedding-3-small": _p("0.02", "0"),
    "text-embedding-ada-002": _p("0.10", "0"),
}

# Used when a model id matches nothing known. Deliberately Opus-priced: an
# unknown model should over-estimate, so an unrecognised id trips the spend cap
# early rather than letting an unmetered build run away.
_UNKNOWN_PRICE = _p("5.00", "25.00")


def _parse_overrides(raw: str) -> dict[str, ModelPrice]:
    """PERITUS_MODEL_PRICES="model:in_per_mtok:out_per_mtok,model2:..."."""
    out: dict[str, ModelPrice] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            logger.warning("Ignoring malformed PERITUS_MODEL_PRICES entry %r", chunk)
            continue
        try:
            out[parts[0].strip()] = _p(parts[1].strip(), parts[2].strip())
        except Exception:
            logger.warning("Ignoring unparseable PERITUS_MODEL_PRICES entry %r", chunk)
    return out


_OVERRIDES = _parse_overrides(settings.PRICE_OVERRIDES)


def price_for(model: str) -> ModelPrice:
    """Resolve a model id (alias or dated snapshot) to its per-MTok price."""
    model = (model or "").strip()
    tables = (_OVERRIDES, _ANTHROPIC_PRICES, _OPENAI_PRICES)
    best: ModelPrice | None = None
    best_len = -1
    for table in tables:
        for prefix, price in table.items():
            if model.startswith(prefix) and len(prefix) > best_len:
                best, best_len = price, len(prefix)
        if best is not None and table is _OVERRIDES:
            # An explicit override always wins outright.
            return best
    if best is None:
        logger.warning("No price known for model %r — using conservative default", model)
        return _UNKNOWN_PRICE
    return best


def message_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    batch: bool = False,
) -> Decimal:
    """Cost of one Claude message, from its reported usage.

    ``batch`` must reflect how the response was actually obtained, never what
    the configuration says batching is set to.
    """
    price = price_for(model)
    multiplier = BATCH_MULTIPLIER if batch else Decimal(1)
    billable_input = (
        Decimal(input_tokens)
        + Decimal(cache_creation_input_tokens) * CACHE_WRITE_MULTIPLIER
        + Decimal(cache_read_input_tokens) * CACHE_READ_MULTIPLIER
    )
    total = billable_input * price.input_per_mtok + Decimal(output_tokens) * price.output_per_mtok
    return (total / _MILLION) * multiplier


def embedding_cost_usd(model: str, tokens: int) -> Decimal:
    """Cost of an embedding call. Embeddings bill input tokens only."""
    price = price_for(model)
    return (Decimal(tokens) * price.input_per_mtok) / _MILLION
