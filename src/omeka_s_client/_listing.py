"""Page parsing and checks for verified listings."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, TypeGuard

import httpx2

from ._urls import KEYS, PAGINATION
from .errors import InvalidResponseError
from .types import Record

# A comma inside angle brackets or a quoted attribute belongs to that link.
_LINK = re.compile(r'<([^>]*)>((?:[^,<"]|"[^"]*")*)')
_REL = re.compile(r'(?:^|;)\s*rel\s*=\s*(?:"([^"]*)"|([^;\s]+))', re.IGNORECASE)


@dataclass(slots=True)
class ListingPage:
    records: list[Record]
    total: int | None
    next_link: str | None
    url: httpx2.URL


class VerificationFailure(Exception):
    pass


def positive_integer(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bad_response(operation: str, resource: str, label: str) -> InvalidResponseError:
    return InvalidResponseError(
        f"{operation} {resource} returned {label}.", operation=operation, resource=resource
    )


def _json(response: httpx2.Response, operation: str, resource: str) -> Any:
    def invalid_constant(value: str) -> None:
        raise ValueError(value)

    try:
        response.read()
        return response.json(parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise _bad_response(operation, resource, "invalid JSON") from None


def record_from(response: httpx2.Response, operation: str, resource: str) -> Record:
    value = _json(response, operation, resource)
    if not isinstance(value, dict):
        raise _bad_response(operation, resource, "a non-object record")
    return value


def parse_page(response: httpx2.Response, url: httpx2.URL, resource: str) -> ListingPage:
    records = _json(response, "GET", resource)
    if not isinstance(records, list) or any(not isinstance(value, dict) for value in records):
        raise _bad_response("GET", resource, "an invalid page of records")
    header = response.headers.get("Omeka-S-Total-Results")
    try:
        total = None if header is None else int(header)
        if header is not None and not re.fullmatch(r"[0-9]+", header.strip()):
            raise ValueError
    except ValueError:
        raise _bad_response("GET", resource, "an invalid total count") from None
    link = None
    for target, params in _LINK.findall(response.headers.get("link", "")):
        rel = _REL.search(params)
        if rel is not None and "next" in (rel[1] or rel[2] or "").lower().split():
            if link is not None or not target:
                raise _bad_response("GET", resource, "an ambiguous next link")
            link = target
    return ListingPage(records, total, link, url)


def check_filters(url: httpx2.URL, filters: list[tuple[str, str]], resource: str) -> None:
    actual = Counter(pair for pair in url.params.multi_items() if pair[0] not in KEYS | PAGINATION)
    expected = Counter(filters)
    # Omeka core adds these defaults when a query omits them.
    defaults = (
        ("sort_by", "id"),
        ("sort_order", "asc"),
        ("sort_by_default", ""),
        ("sort_order_default", ""),
    )
    for name, default in defaults:
        if all(key != name for key, _ in expected) and actual[(name, default)] == 1:
            del actual[(name, default)]
    if actual != expected:
        raise _bad_response("GET", resource, "a link with different filters")


def page_key(url: httpx2.URL) -> tuple[str, tuple[tuple[str, str], ...]]:
    pairs = sorted(url.params.multi_items())
    return str(url.copy_with(query=None, fragment=None)), tuple(pairs)


def verified_ids(records: list[Record], seen: set[int], total: int | None) -> None:
    bad: set[int] = set()
    for record in records:
        value = record.get("o:id")
        if not positive_integer(value):
            raise VerificationFailure(f"Invalid record ID after {len(seen)} unique IDs.")
        if value in seen:
            bad.add(value)
        seen.add(value)
    if bad:
        raise VerificationFailure(
            f"{len(seen)} unique IDs, expected count {total}. "
            f"Duplicate IDs include {sorted(bad)[:10]}."
        )


def verify_end(ids: set[int], total: int | None, expected: set[int] | None) -> None:
    if total is None and expected is None:
        raise VerificationFailure(f"No count or expected IDs. Received {len(ids)} unique IDs.")
    if expected is not None and expected != ids:
        missing = sorted(expected - ids)[:10]
        unexpected = sorted(ids - expected)[: 10 - len(missing)]
        raise VerificationFailure(
            f"Received {len(ids)} IDs, expected {len(expected)}. "
            f"Missing examples: {missing}. Unexpected examples: {unexpected}."
        )
    if total is not None and len(ids) != total:
        raise VerificationFailure(f"Received {len(ids)} unique IDs, expected count {total}.")
