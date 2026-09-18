from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """One cited passage, numbered to match the inline ``[n]`` markers — the
    exact shape the SSE ``sources`` event emits and JSONB stores.

    That last clause was a promise the model broke. It declared three fields,
    so every field the stream had added since — the passage text itself, the
    dispute flags — was **discarded on the way out**: the row on disk kept them
    (`conversation_repository` stores the dict untouched), the stream showed
    them, and a reload lost them. The chat's cited-passage panel duly fell back
    to "this answer was saved before passages were kept" for answers written
    the same hour.

    Anything `used_citations()` puts on a citation belongs here.
    """

    n: int
    label: str
    source_id: int | None = None
    #: The passage, trimmed by the API. Absent on answers stored before it was
    #: sent, which is what the client's fallback is for.
    text: str | None = None
    #: The chunk this passage came from, so a reader can be shown what surrounds
    #: it. Absent for the same reason as ``text``.
    chunk_id: int | None = None
    #: This passage is on one side of a disagreement in the corpus.
    disputed: bool = False
    dispute_points: list[str] = Field(default_factory=list)


class ConversationMessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[Citation] | None = None
    has_contradiction: bool = False
    interrupted: bool = False
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    expert_id: int
    # Joined expert columns so lists render without a second fetch. `expert_slug`
    # is experts.name (the URL slug); `expert_persona_name` is the display name.
    expert_slug: str
    expert_topic: str
    expert_persona_name: str | None = None
    expert_status: str
    # The found picture's version (migration 027), or None when the expert has
    # none. Only the version: a chat row renders the tile at 20px and carries no
    # credit line, so the rest of the provenance would be dead weight on every
    # sidebar fetch. The image itself is at GET /experts/{expert_slug}/picture.
    expert_picture_version: str | None = None
    title: str | None = None
    message_count: int = 0
    created_at: datetime
    last_message_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageOut] = []


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class SendMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v
