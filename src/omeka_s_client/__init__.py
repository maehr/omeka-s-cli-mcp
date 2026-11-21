"""Typed Python client for the Omeka S REST API."""

from __future__ import annotations

from ._http import VERSION as __version__
from .client import OmekaClient
from .errors import (
    ConfigurationError,
    DownloadError,
    IncompleteListingError,
    InvalidResponseError,
    ListingLimitError,
    OmekaConnectionError,
    OmekaError,
    OmekaHTTPError,
    RDFReplacementRequiredError,
    SnapshotConsistencyError,
    SnapshotError,
    UnsafeRedirectError,
    WriteOutcomeUnknownError,
)
from .filters import PropertyCondition, property_filter, property_filters
from .snapshots import Snapshot, capture_snapshot, read_snapshot, write_snapshot
from .transport import ConnectFailed, ResponseLost, Transport, TransportRequest, TransportResponse
from .types import DownloadResult, Page, QueryParams, Record, Upload

__all__ = [
    "ConfigurationError",
    "ConnectFailed",
    "DownloadError",
    "DownloadResult",
    "IncompleteListingError",
    "InvalidResponseError",
    "ListingLimitError",
    "OmekaClient",
    "OmekaConnectionError",
    "OmekaError",
    "OmekaHTTPError",
    "Page",
    "PropertyCondition",
    "QueryParams",
    "RDFReplacementRequiredError",
    "Record",
    "ResponseLost",
    "Snapshot",
    "SnapshotConsistencyError",
    "SnapshotError",
    "Transport",
    "TransportRequest",
    "TransportResponse",
    "UnsafeRedirectError",
    "Upload",
    "WriteOutcomeUnknownError",
    "__version__",
    "capture_snapshot",
    "property_filter",
    "property_filters",
    "read_snapshot",
    "write_snapshot",
]
