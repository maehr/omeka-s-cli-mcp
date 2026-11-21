"""Exceptions raised by Omeka client operations."""

from __future__ import annotations


class OmekaError(Exception):
    """Describe an operation failure without exposing request credentials.

    >>> OmekaError("Request failed.", operation="GET", status=503).status
    503
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        resource: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.resource = resource
        self.status = status


class ConfigurationError(OmekaError, ValueError):
    """Report an invalid client or request option."""


class OmekaHTTPError(OmekaError):
    """Report an HTTP response outside the successful status range."""


class OmekaConnectionError(OmekaError):
    """Report an exhausted read or a write that was not sent."""


class WriteOutcomeUnknownError(OmekaError):
    """Report a write whose response was lost after a possible send."""


class InvalidResponseError(OmekaError):
    """Report a response that does not match the API contract."""


class IncompleteListingError(OmekaError):
    """Report an exhausted listing verification failure."""


class UnsafeRedirectError(OmekaError):
    """Report a redirect or pagination link outside the API root."""


class RDFReplacementRequiredError(OmekaError, ValueError):
    """Report a PATCH that needs explicit permission to replace RDF values."""


class SnapshotError(OmekaError):
    """Report invalid snapshot files or a snapshot write failure."""


class SnapshotConsistencyError(SnapshotError):
    """Report inconsistent item or media relationships during capture."""


class DownloadError(OmekaError):
    """Report a failed download."""


class ListingLimitError(OmekaError):
    """Report a listing that exceeds its caller's record limit."""
