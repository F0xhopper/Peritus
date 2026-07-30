"""Persistence for stateful expert conversations.

Conversations are owner-scoped exactly like experts (see
``experts.repository._visibility_clause``): regular users see only their own
rows, admins additionally see legacy ``owner_id IS NULL`` rows. Callers get
``None``/``False`` for rows outside their scope and must map that to 404 —
never 403 — so other users' conversation ids stay unguessable.

Message ordering relies on ``conversation_messages.id`` (BIGSERIAL): the
streaming claim guarantees one writer per conversation, so insert order is
chronological.
"""

import json
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from peritus.experts.repository import _visibility_clause

# A crashed stream's claim self-heals after this window, so a conversation can
# never be locked out of new answers permanently.
STREAM_CLAIM_STALE_MINUTES = 3


@dataclass
class Conversation:
    id: str
    expert_id: int
    owner_id: str | None
    title: str | None
    message_count: int
    streaming_started_at: datetime | None
    created_at: datetime
    last_message_at: datetime
    # Joined expert columns, populated by the list/get queries so summary
    # responses never need a second fetch.
    expert_slug: str | None = None
    expert_topic: str | None = None
    expert_persona_name: str | None = None
    expert_status: str | None = None


@dataclass
class ConversationMessage:
    id: int
    conversation_id: str
    role: str
    content: str
    citations: list[dict] | None
    has_contradiction: bool
    interrupted: bool
    created_at: datetime


_EXPERT_JOIN_COLUMNS = """
    e.name AS expert_slug,
    e.topic AS expert_topic,
    e.persona_name AS expert_persona_name,
    e.status AS expert_status
"""


class ConversationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, expert_id: int, owner_id: str | None) -> Conversation:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (expert_id, owner_id)
                VALUES ($1, $2::uuid)
                RETURNING *
                """,
                expert_id, owner_id,
            )
        return _row_to_conversation(row)

    async def get_for_user(
        self, conversation_id: str, owner_id: str, include_unowned: bool
    ) -> Conversation | None:
        clause, params = _visibility_clause(owner_id, include_unowned, alias="c", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT c.*, {_EXPERT_JOIN_COLUMNS}
                FROM conversations c
                JOIN experts e ON e.id = c.expert_id
                WHERE c.id = $1::uuid AND {clause}
                """,
                conversation_id, *params,
            )
        return _row_to_conversation(row) if row else None

    async def list_recent_for_user(
        self, owner_id: str, include_unowned: bool, limit: int
    ) -> list[Conversation]:
        """Cross-expert recents for the sidebar. Empty conversations (created
        but never sent a message) are invisible by design."""
        clause, params = _visibility_clause(owner_id, include_unowned, alias="c", idx=2)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.*, {_EXPERT_JOIN_COLUMNS}
                FROM conversations c
                JOIN experts e ON e.id = c.expert_id
                WHERE {clause} AND c.message_count > 0
                ORDER BY c.last_message_at DESC
                LIMIT $1
                """,
                limit, *params,
            )
        return [_row_to_conversation(r) for r in rows]

    async def list_for_expert(self, expert_id: int, limit: int = 50) -> list[Conversation]:
        """Per-expert history. The caller has already resolved the expert
        through its own ownership check, so no visibility clause here."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.*, {_EXPERT_JOIN_COLUMNS}
                FROM conversations c
                JOIN experts e ON e.id = c.expert_id
                WHERE c.expert_id = $1 AND c.message_count > 0
                ORDER BY c.last_message_at DESC
                LIMIT $2
                """,
                expert_id, limit,
            )
        return [_row_to_conversation(r) for r in rows]

    async def rename(
        self, conversation_id: str, owner_id: str, include_unowned: bool, title: str
    ) -> bool:
        clause, params = _visibility_clause(owner_id, include_unowned, alias="conversations", idx=3)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE conversations SET title = $2 WHERE id = $1::uuid AND {clause}",
                conversation_id, title, *params,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def delete(
        self, conversation_id: str, owner_id: str, include_unowned: bool
    ) -> bool:
        clause, params = _visibility_clause(owner_id, include_unowned, alias="conversations", idx=2)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM conversations WHERE id = $1::uuid AND {clause}",
                conversation_id, *params,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def get_messages(self, conversation_id: str) -> list[ConversationMessage]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation_messages
                WHERE conversation_id = $1::uuid
                ORDER BY id
                """,
                conversation_id,
            )
        return [_row_to_message(r) for r in rows]

    async def recent_history(self, conversation_id: str, limit: int) -> list[dict]:
        """The last ``limit`` messages as ``{role, content}`` dicts, oldest
        first — the exact shape the stateless endpoint receives from clients,
        so ``build_composition_messages`` (and its prompt-cache breakpoints)
        behaves identically."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM conversation_messages
                    WHERE conversation_id = $1::uuid
                    ORDER BY id DESC
                    LIMIT $2
                ) latest ORDER BY id
                """,
                conversation_id, limit,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def claim_stream(self, conversation_id: str) -> bool:
        """Optimistically claim the one-streaming-answer-at-a-time slot.

        Advisory locks would need a pinned connection for the stream's whole
        duration; a timestamp claim doesn't, and a claim orphaned by a crash
        self-heals once it goes stale.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE conversations
                SET streaming_started_at = now()
                WHERE id = $1::uuid
                  AND (streaming_started_at IS NULL
                       OR streaming_started_at < now() - interval '{STREAM_CLAIM_STALE_MINUTES} minutes')
                RETURNING id
                """,
                conversation_id,
            )
        return row is not None

    async def release_claim(self, conversation_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET streaming_started_at = NULL WHERE id = $1::uuid",
                conversation_id,
            )

    async def add_user_message(
        self, conversation_id: str, content: str, fallback_title: str
    ) -> Conversation:
        """Insert the user's question; on the conversation's first message the
        title is set from it (COALESCE keeps later renames/titles intact)."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO conversation_messages (conversation_id, role, content)
                VALUES ($1::uuid, 'user', $2)
                """,
                conversation_id, content,
            )
            row = await conn.fetchrow(
                """
                UPDATE conversations
                SET message_count = message_count + 1,
                    last_message_at = now(),
                    title = COALESCE(title, $2)
                WHERE id = $1::uuid
                RETURNING *
                """,
                conversation_id, fallback_title,
            )
        return _row_to_conversation(row)

    async def finish_stream(
        self,
        conversation_id: str,
        content: str,
        citations: list[dict] | None,
        has_contradiction: bool,
        interrupted: bool,
    ) -> None:
        """End-of-stream persistence, one transaction for every exit path.

        With content: insert the assistant message (partial answers get
        ``interrupted = true``), bump counters, clear the claim. With no
        content (zero tokens arrived): just clear the claim — the orphaned
        user message stays and the UI offers retry.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            if content:
                await conn.execute(
                    """
                    INSERT INTO conversation_messages
                        (conversation_id, role, content, citations, has_contradiction, interrupted)
                    VALUES ($1::uuid, 'assistant', $2, $3::jsonb, $4, $5)
                    """,
                    conversation_id, content,
                    json.dumps(citations) if citations is not None else None,
                    has_contradiction, interrupted,
                )
                await conn.execute(
                    """
                    UPDATE conversations
                    SET message_count = message_count + 1,
                        last_message_at = now(),
                        streaming_started_at = NULL
                    WHERE id = $1::uuid
                    """,
                    conversation_id,
                )
            else:
                await conn.execute(
                    "UPDATE conversations SET streaming_started_at = NULL WHERE id = $1::uuid",
                    conversation_id,
                )


def _row_to_conversation(row: asyncpg.Record) -> Conversation:
    # Materialised — `row.keys()` is a one-shot iterator, and the four `in`
    # checks below would consume it (see _row_to_expert for the same trap).
    keys = set(row.keys())
    return Conversation(
        id=str(row["id"]),
        expert_id=row["expert_id"],
        owner_id=str(row["owner_id"]) if row["owner_id"] else None,
        title=row["title"],
        message_count=row["message_count"],
        streaming_started_at=row["streaming_started_at"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
        expert_slug=row["expert_slug"] if "expert_slug" in keys else None,
        expert_topic=row["expert_topic"] if "expert_topic" in keys else None,
        expert_persona_name=row["expert_persona_name"] if "expert_persona_name" in keys else None,
        expert_status=row["expert_status"] if "expert_status" in keys else None,
    )


def _row_to_message(row: asyncpg.Record) -> ConversationMessage:
    raw = row["citations"]
    citations = json.loads(raw) if isinstance(raw, str) else raw
    return ConversationMessage(
        id=row["id"],
        conversation_id=str(row["conversation_id"]),
        role=row["role"],
        content=row["content"],
        citations=citations,
        has_contradiction=row["has_contradiction"],
        interrupted=row["interrupted"],
        created_at=row["created_at"],
    )
