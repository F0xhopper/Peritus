"""FastAPI dependency injection helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from application.use_cases.create_expert import get_expert
from core.exceptions import ExpertNotFoundError
from domain.entities import Expert, ExpertStatus


async def require_expert(slug: str) -> Expert:
    """
    Dependency that resolves an expert slug to an Expert entity.

    Raises 404 if not found, 409 if not ready.
    """
    expert = get_expert(slug)
    if not expert:
        raise HTTPException(status_code=404, detail=f"Expert '{slug}' not found.")
    if expert.status != ExpertStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Expert '{slug}' is not yet ready (status: {expert.status.value}).",
        )
    return expert
