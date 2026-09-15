from datetime import datetime

from pydantic import BaseModel

from peritus.api.schemas.experts import ExpertAvatar, ExpertPictureOut
from peritus.experts.domain import ExpertAccess


class ShareStateOut(BaseModel):
    """The owner's view of an expert's share link.

    ``token`` is null while sharing is off. The API does not know the web app's
    origin, so the client builds the URL (``/share/{token}``).
    """

    enabled: bool
    token: str | None = None
    created_at: datetime | None = None
    # People who have opened this link while signed in. Resets with the link.
    viewer_count: int = 0
    # Kept sources the owner uploaded. Viewers can read passages from them, so
    # the share dialog says so before the owner turns sharing on.
    uploaded_source_count: int = 0


class SharedExpertOut(BaseModel):
    """What anyone holding a live share link sees, signed in or not.

    The link preview and the share page render from this. It is the catalog
    card's shape minus curation, plus the avatar recipe: no slug, no owner, no
    error, no build internals — nothing the link's holder could not see after
    opening it, and nothing about who shared it.
    """

    topic: str
    tier: str
    readiness: str = "pending"
    graph_expanded: bool = False
    build_active: bool | None = None
    persona_name: str | None = None
    persona_bio: str | None = None
    key_concepts: list[str] = []
    source_count: int = 0
    chunk_count: int = 0
    node_count: int = 0
    avg_quality: float | None = None
    source_type_counts: dict[str, int] = {}
    avatar: ExpertAvatar | None = None
    picture: ExpertPictureOut | None = None
    created_at: datetime


class ShareAcceptOut(BaseModel):
    """Where to send someone who has just opened a link while signed in."""

    slug: str
    access: ExpertAccess
