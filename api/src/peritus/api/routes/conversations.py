"""Stateful expert conversations — the web dashboard's chat surface.

Additive to the stateless ``POST /experts/{slug}/chat`` (which stays the
TUI/CLI contract): conversations persist every turn to Postgres, so chats are
resumable, listed as sidebar recents, and safe against refresh mid-answer.

Conventions carried over from the experts routes: owner-scoped everywhere,
rows outside the caller's scope 404 (never 403), and logs carry ids and
timings only — never message content.
"""

import asyncio
import contextlib
import json
import uuid

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from peritus.api.auth import AuthUser, require_user
from peritus.api.ratelimit import chat_rate_limit
from peritus.api.schemas.conversations import (
    ConversationDetail,
    ConversationMessageOut,
    ConversationSummary,
    RenameConversationRequest,
    SendMessageRequest,
)
from peritus.chat.conversation_repository import Conversation, ConversationRepository
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.anthropic_batch import provider_error_message
from peritus.infrastructure.database import get_pool
from peritus.search.readiness import get_readiness

logger = get_logger(__name__)

router = APIRouter(tags=["conversations"])

_TITLE_MAX_CHARS = 60


def _title_from_question(question: str) -> str:
    """First-message auto-title: the question collapsed to one line and cut at
    a word boundary. Deliberately not LLM-generated (cost decision)."""
    collapsed = " ".join(question.split())
    # Sentence case: questions are typed in whatever casing, and a sidebar of
    # "what is the potency" beside "Why can we not…" scans as unfinished.
    collapsed = collapsed[:1].upper() + collapsed[1:]
    if len(collapsed) <= _TITLE_MAX_CHARS:
        return collapsed
    cut = collapsed[:_TITLE_MAX_CHARS]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def _to_summary(c: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=c.id,
        expert_id=c.expert_id,
        expert_slug=c.expert_slug or "",
        expert_topic=c.expert_topic or "",
        expert_persona_name=c.expert_persona_name,
        expert_status=c.expert_status or "",
        expert_picture_version=c.expert_picture_version,
        title=c.title,
        message_count=c.message_count,
        created_at=c.created_at,
        last_message_at=c.last_message_at,
    )


def _summary_from_expert(c: Conversation, expert: Expert) -> ConversationSummary:
    """Summary for a conversation fetched without the expert join."""
    c.expert_slug = expert.name
    c.expert_topic = expert.topic
    c.expert_persona_name = expert.persona_name
    c.expert_status = expert.status.value
    c.expert_picture_version = expert.picture.version if expert.picture else None
    return _to_summary(c)


async def _get_owned_expert(slug: str, user: AuthUser) -> Expert:
    repo = ExpertRepository(get_pool())
    expert = await repo.get_for_user(slug, user.id, include_unowned=user.is_admin)
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return expert


async def _get_owned_conversation(conversation_id: uuid.UUID, user: AuthUser) -> Conversation:
    convs = ConversationRepository(get_pool())
    conv = await convs.get_for_user(str(conversation_id), user.id, include_unowned=user.is_admin)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("/experts/{slug}/conversations", response_model=ConversationSummary)
async def create_conversation(slug: str, user: AuthUser = Depends(require_user)):
    """Create an empty conversation. The web client calls this on the first
    send, so empties are transient; recents filter them out regardless."""
    expert = await _get_owned_expert(slug, user)
    # Retrieval readiness, not job status — see routes/chat.py.
    readiness = await get_readiness(get_pool(), expert.id)
    if not readiness.can_chat:
        raise HTTPException(status_code=409, detail=f"Expert is {readiness.label}")
    conv = await ConversationRepository(get_pool()).create(expert.id, user.id)
    logger.info("Created conversation %s for expert %d", conv.id, expert.id)
    return _summary_from_expert(conv, expert)


@router.get("/experts/{slug}/conversations", response_model=list[ConversationSummary])
async def list_expert_conversations(slug: str, user: AuthUser = Depends(require_user)):
    expert = await _get_owned_expert(slug, user)
    convs = await ConversationRepository(get_pool()).list_for_expert(expert.id)
    return [_to_summary(c) for c in convs]


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_recent_conversations(
    limit: int = Query(20, ge=1, le=50),
    user: AuthUser = Depends(require_user),
):
    convs = await ConversationRepository(get_pool()).list_recent_for_user(
        user.id, include_unowned=user.is_admin, limit=limit
    )
    return [_to_summary(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user: AuthUser = Depends(require_user)
):
    conv = await _get_owned_conversation(conversation_id, user)
    messages = await ConversationRepository(get_pool()).get_messages(conv.id)
    summary = _to_summary(conv)
    return ConversationDetail(
        **summary.model_dump(),
        messages=[
            ConversationMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=m.citations,  # type: ignore[arg-type]
                has_contradiction=m.has_contradiction,
                interrupted=m.interrupted,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: uuid.UUID,
    req: RenameConversationRequest,
    user: AuthUser = Depends(require_user),
):
    convs = ConversationRepository(get_pool())
    renamed = await convs.rename(
        str(conversation_id), user.id, include_unowned=user.is_admin, title=req.title
    )
    if not renamed:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = await convs.get_for_user(
        str(conversation_id), user.id, include_unowned=user.is_admin
    )
    assert conv is not None
    return _to_summary(conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, user: AuthUser = Depends(require_user)
):
    deleted = await ConversationRepository(get_pool()).delete(
        str(conversation_id), user.id, include_unowned=user.is_admin
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    logger.info("Deleted conversation %s", conversation_id)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    req: SendMessageRequest,
    user: AuthUser = Depends(chat_rate_limit),
):
    """Send a question and stream the answer (SSE), persisting both turns.

    Event protocol is the stateless endpoint's plus a leading ``meta`` event
    (``conversation_id`` + ``title``) so the client can update sidebar/URL
    without a second fetch.

    Throttled per user on the same budget as the stateless endpoint: the two
    surfaces cost the same to serve, so one must not be a way around the other.
    """
    pool = get_pool()
    convs = ConversationRepository(pool)
    conv = await _get_owned_conversation(conversation_id, user)

    expert = await ExpertRepository(pool).get_by_id(conv.expert_id)
    if not expert:
        # Deletion cascades the conversation away, so a missing expert here can
        # only be a race with an in-flight delete.
        raise HTTPException(status_code=409, detail="Expert is deleted")
    # A rebuild resets readiness to pending before it wipes the corpus, so this
    # also catches an expert whose sources are being replaced underneath us.
    readiness = await get_readiness(pool, expert.id)
    if not readiness.can_chat:
        raise HTTPException(status_code=409, detail=f"Expert is {readiness.label}")

    if not await convs.claim_stream(conv.id):
        raise HTTPException(status_code=409, detail="An answer is already streaming")

    try:
        # History for the model: everything before this question, in the exact
        # {role, content} shape stateless clients send. +1 covers the reused-
        # question case below; build_composition_messages caps at the max.
        history = await convs.recent_history(
            conv.id, settings.CHAT_HISTORY_MAX_MESSAGES + 1
        )
        if history and history[-1]["role"] == "user" and history[-1]["content"] == req.question:
            # Retry of an orphaned question (its stream died before any tokens):
            # reuse the stored user message instead of inserting a duplicate.
            history = history[:-1]
        else:
            conv = await convs.add_user_message(
                conv.id, req.question, fallback_title=_title_from_question(req.question)
            )
    except Exception:
        await convs.release_claim(conv.id)
        raise

    logger.info(
        "Streaming answer for conversation %s (expert=%d, history=%d)",
        conv.id, expert.id, len(history),
    )
    return EventSourceResponse(
        _stream_and_persist(pool, convs, conv, expert, req.question, history)
    )


def answer_error_message(error: BaseException) -> str:
    """What to tell the reader when an answer dies mid-flight.

    A provider refusal is not an internal error, and calling it one throws away
    the only sentence that says how to fix it. The build path already surfaces
    the provider's own wording (``provider_error_message``), so an empty credit
    balance fails a build with "the Anthropic API rejected every request: Your
    credit balance is too low…" — while the identical failure in a chat said
    "the expert hit an internal error while answering", and the owner had no way
    to tell a billing problem from a bug in retrieval.

    The caller owns the expert, so the provider's own message is theirs to see.
    It is still trimmed: an SDK message is a sentence, and anything longer than
    one is not something a reader wants in a notice.
    """
    if isinstance(error, anthropic.APIStatusError):
        detail = provider_error_message(error)[:300].strip()
        return (
            "The answer could not be composed — the Anthropic API rejected the "
            f"request: {detail}"
        )
    return "The expert hit an internal error while answering."


async def _stream_and_persist(
    pool: asyncpg.Pool,
    convs: ConversationRepository,
    conv: Conversation,
    expert: Expert,
    question: str,
    history: list[dict],
):
    """Wrap the shared stream body with persistence for every exit path.

    - ``done``: assistant message persisted (citations + contradiction flag),
      claim cleared — before the ``done`` event is emitted, so a client that
      vanishes right after still finds the full answer on refresh.
    - generation error: whatever streamed is persisted ``interrupted``, the
      client gets the same ``error`` event the stateless endpoint emits.
    - client disconnect / cancellation: same partial persistence, shielded so
      it completes even though this task is being torn down. Zero tokens →
      nothing persisted, claim cleared; the orphaned question supports retry.
    """
    answer_parts: list[str] = []
    citations: list[dict] | None = None
    has_contradiction = False
    finalized = False

    async def _finalize(interrupted: bool) -> None:
        nonlocal finalized
        if finalized:
            return
        finalized = True
        await convs.finish_stream(
            conv.id,
            "".join(answer_parts),
            citations,
            has_contradiction,
            interrupted=interrupted,
        )

    try:
        yield {"data": json.dumps({
            "type": "meta", "conversation_id": conv.id, "title": conv.title,
        })}

        from peritus.chat.streaming import stream_expert_answer

        # conversation_id ties this answer's retrieval audit to the transcript,
        # so a persisted answer can be accounted for long after its stream ends.
        async for event in stream_expert_answer(
            pool, expert, question, history, conversation_id=conv.id
        ):
            if event["type"] == "token":
                answer_parts.append(event["text"])
            elif event["type"] == "sources":
                citations = event["citations"]
                has_contradiction = event["has_contradiction"]
            elif event["type"] == "done":
                # An answer cut off at the length limit is stored as interrupted,
                # so the transcript marks it and offers to ask again instead of
                # presenting half an answer as a whole one.
                await _finalize(interrupted=bool(event.get("truncated")))
            yield {"data": json.dumps(event)}

    except Exception as error:
        logger.exception("Conversation stream failed for %s", conv.id)
        with contextlib.suppress(Exception):
            await _finalize(interrupted=True)
        yield {"data": json.dumps({
            "type": "error",
            "message": answer_error_message(error),
        })}

    finally:
        if not finalized:
            # Cancellation path (client gone, server stopping): shield the
            # write so it survives this task's teardown. If even that fails,
            # the stale-claim window self-heals the conversation.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(_finalize(interrupted=True))
