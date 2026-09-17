"""Provider-specific data source implementations."""


class ETLStageError(RuntimeError):
    """Identify the source and stage which raised an ETL exception."""

    def __init__(self, *, source: str, stage: str, cause: Exception) -> None:
        self.source = source
        self.stage = stage
        self.cause = cause
        super().__init__(
            f"{source} stage={stage} failed: {type(cause).__name__}: {cause}",
        )
