"""Erros de fonte e configuração."""


class Osint4AllError(Exception):
    pass


class ConfigurationError(Osint4AllError):
    pass


class FailedSource(Osint4AllError):
    pass


class FailedAuthentication(FailedSource):
    pass


class FailedRateLimit(FailedSource):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FailedTimeout(FailedSource):
    pass


class SkippedDisabled(Osint4AllError):
    pass
