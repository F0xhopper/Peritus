"""Domain and application exceptions."""


class PeritusError(Exception):
    """Base exception for all Peritus errors."""


class ExpertNotFoundError(PeritusError):
    """Expert with given slug does not exist."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Expert '{slug}' not found.")


class ExpertAlreadyExistsError(PeritusError):
    """Expert with given slug already exists."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Expert '{slug}' already exists.")


class IndexBuildError(PeritusError):
    """Failed to build PropertyGraphIndex."""


class SourceIngestionError(PeritusError):
    """Failed to ingest sources for a topic."""


class CourseGenerationError(PeritusError):
    """Failed to generate course from expert."""


class ConversationError(PeritusError):
    """Error during expert conversation."""


class InfrastructureError(PeritusError):
    """Low-level infrastructure error."""
