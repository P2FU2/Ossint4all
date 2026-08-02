"""Exceções tipadas do serviço."""

from __future__ import annotations


class MonitorJusError(Exception):
    """Erro base."""

    code: str = "GENERIC_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.message = message


class SourceOutcomeError(MonitorJusError):
    """Outcome tipado de fonte (skip ou falha)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message, code=code)


class SkippedDisabled(SourceOutcomeError):
    def __init__(self, message: str = "Módulo desabilitado") -> None:
        super().__init__("SKIPPED_DISABLED", message)


class SkippedNotContracted(SourceOutcomeError):
    def __init__(self, message: str = "Produto não contratado") -> None:
        super().__init__("SKIPPED_NOT_CONTRACTED", message)


class FailedAuthentication(SourceOutcomeError):
    def __init__(self, message: str = "Falha de autenticação") -> None:
        super().__init__("FAILED_AUTHENTICATION", message)


class FailedRateLimit(SourceOutcomeError):
    def __init__(self, message: str = "Rate limit", *, retry_after: float | None = None) -> None:
        super().__init__("FAILED_RATE_LIMIT", message)
        self.retry_after = retry_after


class FailedTimeout(SourceOutcomeError):
    def __init__(self, message: str = "Timeout") -> None:
        super().__init__("FAILED_TIMEOUT", message)


class FailedSource(SourceOutcomeError):
    def __init__(self, message: str = "Falha na fonte") -> None:
        super().__init__("FAILED_SOURCE", message)


class PermanentJobError(MonitorJusError):
    """Erro não recuperável — job deve ir para DEAD."""

    recoverable = False


class JobCancelledError(MonitorJusError):
    """Job cancelado pela UI/admin — não vai para DEAD nem RETRY."""

    code = "CANCELLED"


class RecoverableJobError(MonitorJusError):
    """Erro recuperável — job pode ir para RETRY."""

    recoverable = True


class WebhookAuthError(MonitorJusError):
    code = "WEBHOOK_AUTH_FAILED"


class ConfigurationError(MonitorJusError):
    code = "CONFIGURATION_ERROR"
