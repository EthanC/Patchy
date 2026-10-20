"""Exception hierarchy shared across Patchy.

Every failure Patchy expects to encounter is raised as a ``PatchyError`` subclass,
so callers can recover from a single title or platform without catching unrelated
programming errors.
"""


class PatchyError(Exception):
    """Base class for all errors raised intentionally by Patchy."""


class ConfigError(PatchyError):
    """The configuration is missing, malformed, or invalid."""


class StorageError(PatchyError):
    """The SQLite database could not be read or written."""


class FetchError(PatchyError):
    """An upstream service could not be reached or returned an error."""

    def __init__(self, url: str, reason: str, *, status: int | None = None) -> None:
        """Describe a failed request.

        Args:
            url: The URL that was requested.
            reason: A short, human-readable description of the failure.
            status: The HTTP status code, when a response was received.
        """
        self.url: str = url
        self.reason: str = reason
        self.status: int | None = status

        super().__init__(f"GET {url} failed: {reason}")


class PayloadError(PatchyError):
    """An upstream service responded, but not with the data Patchy expected."""


class TitleNotFoundError(PayloadError):
    """The upstream service does not know the requested title."""


class NotificationError(PatchyError):
    """A notification could not be delivered."""
