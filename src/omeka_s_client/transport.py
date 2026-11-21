"""Injectable HTTP transport for offline tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """Carry one request to an injected transport.

    >>> TransportRequest("GET", "https://example.org/api/items").content
    b''
    """

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes = b""


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """Carry response data or an iterable of response chunks.

    >>> TransportResponse(200, content=(b"a", b"bc")).status
    200
    """

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes | Iterable[bytes] = b""


class Transport(Protocol):
    """Process one request and return a response."""

    def __call__(self, request: TransportRequest, /) -> TransportResponse: ...


class ConnectFailed(Exception):
    """Signal a transport failure before the request was sent.

    >>> str(ConnectFailed("Unreachable host"))
    'Unreachable host'
    """


class ResponseLost(Exception):
    """Signal a transport failure after the request was sent.

    >>> str(ResponseLost("Response interrupted"))
    'Response interrupted'
    """
