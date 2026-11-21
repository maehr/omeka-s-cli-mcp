"""URL validation and query handling."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from urllib.parse import unquote, unquote_plus, urlencode

import httpx2

from .errors import ConfigurationError
from .types import QueryParams, Scalar

KEYS = frozenset({"key_identity", "key_credential"})
PAGINATION = frozenset({"page", "per_page"})


def _has_userinfo(url: httpx2.URL) -> bool:
    return b"@" in url.netloc or bool(url.userinfo)


def http_url(url: httpx2.URL) -> bool:
    return url.scheme in {"http", "https"} and bool(url.host) and not _has_userinfo(url)


def installation_url(base: str) -> str:
    try:
        url = httpx2.URL(base)
    except (httpx2.InvalidURL, TypeError):
        raise ConfigurationError("Invalid Omeka installation URL.") from None
    if not http_url(url) or re.search(r"[?#]", base):
        raise ConfigurationError("Invalid Omeka installation URL.")
    if "@" in base.split("//", 1)[-1].split("/", 1)[0]:
        raise ConfigurationError("Invalid Omeka installation URL.")
    if _path(url) is None:
        raise ConfigurationError("Invalid Omeka installation path.")
    return str(url).rstrip("/").removesuffix("/api")


def _path(url: httpx2.URL) -> tuple[str, ...] | None:
    raw_path = url.raw_path.split(b"?", 1)[0].decode("ascii")
    segments = []
    for segment in raw_path.split("/"):
        decoded = unquote(segment)
        if decoded in {".", ".."} or re.search(r"[/\\%\x00-\x1f\x7f]", decoded):
            return None
        segments.append(decoded)
    return tuple(segments)


def _origin(url: httpx2.URL) -> tuple[str, str, int]:
    default_port = 443 if url.scheme == "https" else 80
    return url.scheme, url.host, default_port if url.port is None else url.port


def under_root(url: httpx2.URL, root: httpx2.URL) -> bool:
    if not http_url(url) or _origin(url) != _origin(root):
        return False
    path = _path(url)
    root_path = _path(root)
    return (
        path is not None
        and root_path is not None
        and len(path) >= len(root_path)
        and path[: len(root_path) - 1] == root_path[:-1]
    )


def _parameter_name(name: str) -> str:
    # PHP normalizes dots and spaces in parameter names and parses bracketed keys.
    return name.lstrip().split("[", 1)[0].replace(".", "_").replace(" ", "_").lower()


def is_key(encoded_name: str) -> bool:
    return _parameter_name(unquote_plus(encoded_name)) in KEYS


def without_keys(url: httpx2.URL) -> httpx2.URL:
    # Preserve the encoding of other parameters, including signed download URLs.
    query = b"&".join(
        pair
        for pair in url.query.split(b"&")
        if not is_key(pair.split(b"=", 1)[0].decode("utf-8", errors="replace"))
    )
    if query == url.query:
        return url
    return url.copy_with(query=query or None)


def query_pairs(filters: QueryParams | None, *, verify: bool) -> list[tuple[str, str]]:
    pairs = (
        [(key, value) for key, values in filters.items() for value in _values(values)]
        if isinstance(filters, Mapping)
        else list(filters or ())
    )
    reserved = KEYS | PAGINATION
    if verify:
        reserved |= {"sort_by", "sort_order"}
    if any(_parameter_name(key) in reserved for key, _ in pairs):
        raise ConfigurationError("Filters contain a reserved key.")
    return [(key, _scalar(value)) for key, value in pairs]


def _values(value: Scalar | Sequence[Scalar]) -> Sequence[Scalar]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    return (value,)


def _scalar(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def add_query(url: httpx2.URL, pairs: list[tuple[str, str]]) -> httpx2.URL:
    query = b"&".join(part for part in (url.query, urlencode(pairs).encode("ascii")) if part)
    return url.copy_with(query=query or None)
