class PeritusError(Exception):
    """Base for all domain errors."""


class NotFoundError(PeritusError):
    def __init__(self, resource: str, identifier: str | int) -> None:
        super().__init__(f"{resource} not found: {identifier}")
        self.resource = resource
        self.identifier = identifier


class ConflictError(PeritusError):
    pass


class BuildError(PeritusError):
    pass


class IngestionError(PeritusError):
    pass


class EmbeddingError(PeritusError):
    pass


class FetchError(PeritusError):
    pass


class ValidationError(PeritusError):
    pass
