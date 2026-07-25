from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """One cited passage, numbered to match the inline ``[n]`` markers — the
    exact shape the SSE ``sources`` event emits and JSONB stores."""
    n: int
    label: str
    source_id: int | None = None


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
