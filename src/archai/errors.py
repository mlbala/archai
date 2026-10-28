class ArchAIError(Exception):
    """Base error with a documented CLI exit code."""

    exit_code = 1


class IncompleteRequirementsError(ArchAIError):
    exit_code = 2


class ProviderError(ArchAIError):
    exit_code = 3


class ValidationError(ArchAIError):
    exit_code = 4


class ExportError(ArchAIError):
    exit_code = 5


class StateConflictError(ArchAIError):
    exit_code = 6
