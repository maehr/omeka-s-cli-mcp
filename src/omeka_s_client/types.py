"""Data types for Omeka records, queries, and files."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

Record: TypeAlias = dict[str, Any]
Scalar: TypeAlias = str | int | float | bool | None
QueryParams: TypeAlias = Mapping[str, Scalar | Sequence[Scalar]] | Sequence[tuple[str, Scalar]]


@dataclass(frozen=True, slots=True)
class Upload:
    """Describe one upload from a path or from bytes.

    >>> Upload(content=b"example", filename="example.txt").filename
    'example.txt'
    """

    path: Path | None = None
    content: bytes | None = None
    filename: str | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        if (self.path is None) == (self.content is None):
            raise ValueError("An upload requires exactly one path or byte content.")


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Give the path, byte count, and SHA-256 digest of a download.

    >>> DownloadResult(Path("file"), 0, "sha256").size
    0
    """

    path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Page:
    """Give the records and pagination information for one page.

    >>> Page([], 0, 1, 50, False).has_next
    False
    """

    records: list[Record]
    total: int | None
    page: int
    per_page: int
    has_next: bool
