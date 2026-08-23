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


class IncompleteBuildError(PeritusError):
    """A build ran to the end without producing every artefact an expert needs.

    Deliberately **not** a :class:`BuildError`. The worker reads BuildError as a
    deterministic dead-end and fails the job on the first attempt (see
    ``BuildWorker._on_failure``), which is right for "this topic yields nothing"
    and wrong for this: a missing graph or persona almost always means one model
    call failed, and the next attempt usually succeeds. Sitting outside that
    branch makes these retry like any other transient fault, and only mark the
    expert failed once the attempts are exhausted.

    ``missing`` names the artefacts that were absent, so the error message says
    what to look for rather than just that something was wrong.
    """

    def __init__(self, missing: list[str]) -> None:
        joined = ", ".join(missing)
        super().__init__(
            f"Build finished without: {joined}. An expert is only ready once its "
            "concepts, concept graph and persona are all present."
        )
        self.missing = missing


class IngestionError(PeritusError):
    pass


class EmbeddingError(PeritusError):
    pass


class FetchError(PeritusError):
    pass


class ValidationError(PeritusError):
    pass
