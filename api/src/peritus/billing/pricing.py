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
    "claude-fable-5": _p("10.00", "50.00"),
    "claude-mythos-5": _p("10.00", "50.00"),
    "claude-opus-5": _p("5.00", "25.00"),
    "claude-opus-4-8": _p("5.00", "25.00"),
    "claude-opus-4-7": _p("5.00", "25.00"),
    "claude-opus-4-6": _p("5.00", "25.00"),
    "claude-opus-4-5": _p("5.00", "25.00"),
    "claude-sonnet-5": _p("3.00", "15.00"),
    "claude-sonnet-4-6": _p("3.00", "15.00"),
    "claude-sonnet-4-5": _p("3.00", "15.00"),
    "claude-haiku-4-5": _p("1.00", "5.00"),
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


# ── Estimating what a source will cost before deciding to keep it ────────────
#
# The meter reports actual spend, but only after the fact, and the expensive
# step — ingestion — happens *after* discovery has already committed to a
# corpus. So the discovery loop needs a forecast rather than a measurement.
#
# What ingestion actually costs, per source:
#   chunks             = text_chars / CHUNK_SIZE_CHARS
#   per chunk          one contextualisation call (FAST_MODEL): a
#                       CONTEXT_MAX_CHARS window plus the chunk in, a short
#                       prefix out; and one embedding of the chunk
#   per GRAPH_BATCH_SIZE chunks   one graph-extraction call (GRAPH_MODEL) whose
#                       input is those chunks' full text
#   plus OCR, priced per page, for sources that took a paid full-text path
#
# Everything except OCR scales with characters, which is the point: a count
# budget treats a 2,000-character blog post and a 120,000-character monograph as
# one unit each, and they differ in cost by two orders of magnitude.

# Characters per token, English prose. The tokenizer is not available offline
# and an exact count is not worth a network call for an estimate — this is the
# standard approximation and it is applied consistently on both sides.
CHARS_PER_TOKEN = Decimal("4")

# Output sizes, from the prompts that produce them: a contextual prefix is a
# sentence or two; a graph extraction batch returns a nodes/edges structure.
_CONTEXT_OUTPUT_TOKENS = Decimal("90")
_GRAPH_OUTPUT_TOKENS = Decimal("700")

# Mistral OCR list price, USD per page. Pages are estimated from characters
# because nothing counts them before the document is parsed.
OCR_USD_PER_PAGE = Decimal("0.001")
CHARS_PER_OCR_PAGE = Decimal("3000")

# Calibration status: ONE data point, and it says these constants are LOW.
#
# 2026-09-08, a STANDARD build of "Thomism": 48 accepted sources, 1,374 chunks.
# The chunk model itself is exact — it predicted 138 graph batches and the build
# ran 138. But the forecast for those sources was $2.45 against $4.73 of
# post-discovery spend, and while that comparison is unfair (post-discovery
# also covers entity resolution, claim reconciliation over 112 concepts, and
# persona, none of which this function models or is meant to), the gap is too
# large to be only those. Treat the current output as a floor.
#
# Under-forecasting is the dangerous direction: the discovery loop spends
# against this number, so a low estimate means a build commits to more corpus
# than its budget covers.
#
# Why the attribution is not sharper: the measurement above came from a bespoke
# script that drove ExpertBuilder directly, and BuildMeter's per-stage
# attribution is set by the *worker* forwarding progress events
# (BuildMeter.observe_event), so every dollar landed in the "other" bucket. To
# calibrate properly, run the build through `peritus-worker` and read
# `GET /experts/{slug}/build/usage`, which returns this forecast beside the
# metered contextualisation and graph-extraction cost, and their signed error.
# Three such builds, then set the constants and the date here.
CALIBRATED_AT: str | None = None


def _tokens(chars: int | Decimal) -> Decimal:
    return Decimal(chars) / CHARS_PER_TOKEN


def estimated_ocr_pages(text_chars: int) -> int:
    """Pages a document of this length is likely to have been OCR'd from."""
    if text_chars <= 0:
        return 0
    return int(
        (Decimal(text_chars) / CHARS_PER_OCR_PAGE).to_integral_value(rounding="ROUND_CEILING")
    )


def estimated_ingest_cost_usd(
    text_chars: int,
    ocr_pages: int = 0,
    batch: bool = False,
) -> Decimal:
    """Forecast of what ingesting one source of this size will cost, in USD.

    ``batch`` should reflect the build's execution policy: a background build
    runs its contextualisation and graph extraction through the Message Batches
    API at half price, and a forecast that ignored that would stop the discovery
    loop at half the corpus it can afford.
    """
    from peritus.core.config import settings as core_settings

    if text_chars <= 0:
        return Decimal(0) + _ocr_cost(ocr_pages)

    chunk_size = max(1, core_settings.CHUNK_SIZE_CHARS)
    chunks = Decimal(max(1, -(-text_chars // chunk_size)))

    total = Decimal(0)

    if core_settings.CONTEXT_ENABLED:
        # Each contextualisation call sees a window of the document plus the
        # chunk itself; the window dominates and is capped.
        window_chars = min(core_settings.CONTEXT_MAX_CHARS, text_chars)
        per_call_input = _tokens(window_chars + chunk_size)
        total += chunks * message_cost_usd(
            core_settings.FAST_MODEL,
            input_tokens=int(per_call_input),
            output_tokens=int(_CONTEXT_OUTPUT_TOKENS),
            batch=batch,
        )

    total += embedding_cost_usd(core_settings.EMBED_MODEL, int(_tokens(text_chars)))

    # Graph extraction reads only the first GRAPH_MAX_CHUNKS_PER_SOURCE chunks of
    # a source (builder._graph_chunk_limit); the rest are embedded, not read.
    # Charging every chunk overstated a 120,000-character paper's graph cost by
    # half and made the discovery loop stop at a corpus smaller than it can afford.
    graph_limit = core_settings.GRAPH_MAX_CHUNKS_PER_SOURCE
    graph_chunks = int(chunks) if graph_limit <= 0 else min(int(chunks), graph_limit)
    graph_chars = min(text_chars, graph_chunks * chunk_size)
    graph_batches = Decimal(max(1, -(-graph_chunks // max(1, core_settings.GRAPH_BATCH_SIZE))))
    total += graph_batches * message_cost_usd(
        core_settings.GRAPH_MODEL,
        input_tokens=int(_tokens(graph_chars) / graph_batches),
        output_tokens=int(_GRAPH_OUTPUT_TOKENS),
        batch=batch,
    )

    return total + _ocr_cost(ocr_pages)


def _ocr_cost(pages: int) -> Decimal:
    return OCR_USD_PER_PAGE * Decimal(max(0, pages))
