from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_MAX_DOC_CHARS = 1500

_TOOL = {
    "name": "rank_passages",
    "description": "Score how well each passage answers the query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rankings": {
                "type": "array",
                "description": "One entry per passage, by its index.",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The passage's index."},
                        "relevance": {
                            "type": "number",
                            "description": "0.0 (irrelevant) to 1.0 (directly answers the query).",
                        },
                    },
                    "required": ["index", "relevance"],
                },
            }
        },
        "required": ["rankings"],
    },
}


async def rerank(
    query: str,
    documents: list[str],
    top_n: int,
) -> list[tuple[int, float]]:
    n = len(documents)
    identity = [(i, 0.0) for i in range(min(n, top_n))]
    if not settings.RERANK_ENABLED or not settings.ANTHROPIC_API_KEY or n <= 1:
        return identity

    try:
        client = get_anthropic_client()
        passages = "\n\n".join(f"[{i}]\n{documents[i][:_MAX_DOC_CHARS]}" for i in range(n))
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=2048,
            system=(
                "You are a search reranker. Score how directly each passage answers "
                "the query. Score every passage exactly once, by its index."
            ),
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "rank_passages"},
            messages=[{
                "role": "user",
                "content": f"Query: {query}\n\nPassages:\n\n{passages}",
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        rankings = block.input.get("rankings", [])

        seen: set[int] = set()
        scored: list[tuple[int, float]] = []
        for r in rankings:
            idx, score = r.get("index"), r.get("relevance")
            if isinstance(idx, int) and 0 <= idx < n and idx not in seen \
                    and isinstance(score, (int, float)):
                seen.add(idx)
                scored.append((idx, float(score)))

        if not scored:
            return identity

        scored.sort(key=lambda x: x[1], reverse=True)
        scored.extend((i, 0.0) for i in range(n) if i not in seen)
        return scored[:top_n]

    except Exception as exc:
        logger.warning("Rerank failed, falling back to RRF order: %s", exc)
        return identity
