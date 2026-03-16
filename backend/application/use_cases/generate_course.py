from __future__ import annotations

from typing import AsyncIterator

from core.exceptions import CourseGenerationError, ExpertNotFoundError
from core.logger import get_logger
from domain.entities import Course, CourseModule, Difficulty, Expert
from infrastructure.graph.llama_graph_repo import load_graph_index
from infrastructure.llm.anthropic_adapter import (
    build_expert_system_prompt,
    stream_completion,
)

logger = get_logger(__name__)

_COURSE_SYSTEM = """You are a master curriculum designer and domain expert.
You will generate a comprehensive, well-structured learning course in clean Markdown.

Course format:
# {title}

## Introduction
(2–3 paragraphs setting context and learning objectives)

## Module 1: {module_title}
### Summary
...
### Key Concepts
- concept 1
- concept 2
### Content
(detailed explanations, examples, analogies, code if relevant)

... (repeat for each module)

## Conclusion
(wrap-up, next steps, further reading suggestions)

Rules:
- Each module = one major concept cluster
- Beginner: 4 modules, simple language, many analogies
- Intermediate: 6 modules, assumes basic knowledge, more technical depth
- Advanced: 8 modules, technical precision, research-level depth
- Custom: tailor to the specified focus area
- Cite concepts using [Source: ...] notation where possible
- Use triple-backtick code blocks with language tag for code
- Do NOT add fluff or marketing language
"""


async def generate_course_stream(
    expert: Expert,
    difficulty: Difficulty,
    focus: str | None = None,
) -> AsyncIterator[str]:
    from domain.entities import ExpertStatus

    if expert.status != ExpertStatus.READY:
        raise ExpertNotFoundError(expert.slug)

    logger.info("generating_course", slug=expert.slug, difficulty=difficulty)

    focus_line = f"\nFocus area: {focus}" if focus else ""
    num_modules = {"beginner": 4, "intermediate": 6, "advanced": 8}.get(
        difficulty.value, 6
    )

    user_message = (
        f"Generate a {difficulty.value} course on '{expert.topic}'.{focus_line}\n"
        f"Create exactly {num_modules} modules.\n"
        f"Draw on your deep knowledge graph of {expert.node_count} concepts and "
        f"{expert.relation_count} relationships.\n"
        f"Expert knowledge summary: {expert.description[:500]}"
    )

    system_prompt = (
        build_expert_system_prompt(expert.topic, expert.description)
        + "\n\n"
        + _COURSE_SYSTEM
    )

    try:
        async for chunk in stream_completion(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ):
            yield chunk
    except Exception as exc:
        logger.error("course_generation_failed", slug=expert.slug, error=str(exc))
        raise CourseGenerationError(
            f"Failed to generate course for '{expert.slug}': {exc}"
        ) from exc
