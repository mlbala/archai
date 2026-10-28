class ArchAIError(Exception):
    """Base error with a documented CLI exit code."""

    exit_code = 1


class IncompleteRequirementsError(ArchAIError):
    exit_code = 2

    def __init__(
        self,
        message: str,
        *,
        question_ids: list[str] | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.question_ids = question_ids or []
        self.run_id = run_id


class ProviderError(ArchAIError):
    exit_code = 3

    def __init__(self, message: str, *, kind: str = "provider_error") -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def fatal(self) -> bool:
        """Authentication and permission failures stop the run instead of falling back."""
        return self.kind in {"authentication", "permission", "configuration"}


class ValidationError(ArchAIError):
    exit_code = 4


class ExportError(ArchAIError):
    exit_code = 5


class StateConflictError(ArchAIError):
    exit_code = 6


class InterviewPaused(ArchAIError):
    """The user chose to save the interview and exit; progress is persisted in the run."""

    exit_code = 130

    def __init__(self, message: str, *, run_id: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
