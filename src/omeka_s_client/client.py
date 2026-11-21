"""Synchronous client for the Omeka S REST API."""

from __future__ import annotations

import builtins
import errno
import hashlib
import json
import math
import mimetypes
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx2

from . import _listing
from ._http import HTTP, FilePart
from ._urls import add_query, http_url, installation_url, query_pairs
from .errors import (
    ConfigurationError,
    DownloadError,
    IncompleteListingError,
    InvalidResponseError,
    ListingLimitError,
    OmekaError,
    RDFReplacementRequiredError,
)
from .transport import Transport
from .types import DownloadResult, Page, QueryParams, Record, Upload

_RESOURCE = re.compile(r"[A-Za-z0-9_-]+")
_NO_LINK = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EPERM}


class OmekaClient:
    """Open a reusable client. Call close when all requests finish.

    >>> from omeka_s_client.testing import FakeOmeka
    >>> with OmekaClient("https://example.org/collection/api/", transport=FakeOmeka()) as client:
    ...     print(client.installation_url)
    https://example.org/collection
    """

    def __init__(
        self,
        base_url: str,
        *,
        key_identity: str | None = None,
        key_credential: str | None = None,
        timeout: float = 30.0,
        transport: Transport | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.installation_url = installation_url(base_url)
        self.api_url = self.installation_url + "/api/"
        if (key_identity is None) != (key_credential is None) or (
            key_identity is not None
            and (not key_identity.strip() or not key_credential or not key_credential.strip())
        ):
            raise ConfigurationError("Supply both Omeka keys or neither key.")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
            or not math.isfinite(timeout)
        ):
            raise ConfigurationError("Timeout must be finite and greater than zero.")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ConfigurationError("Maximum retries must be a nonnegative integer.")
        keys = (
            [("key_identity", key_identity), ("key_credential", key_credential)]
            if key_identity is not None and key_credential is not None
            else []
        )
        self._http = HTTP(self.api_url, keys, timeout, transport, max_retries, sleep)

    def close(self) -> None:
        """Close the underlying API and file clients.

        >>> client = OmekaClient("https://example.org")
        >>> client.close()
        """
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _endpoint(self, resource: str, id: int | None = None) -> httpx2.URL:
        if not isinstance(resource, str) or not _RESOURCE.fullmatch(resource):
            raise ConfigurationError("Invalid Omeka resource name.")
        suffix = resource if id is None else f"{resource}/{id}"
        return self._http.root.join(suffix)

    def get(self, resource: str, id: int) -> Record:
        """Read one record by positive integer ID.

        >>> from omeka_s_client.testing import FakeOmeka
        >>> fake = FakeOmeka({"items": [{"o:id": 7}]})
        >>> with OmekaClient("https://example.org", transport=fake) as client:
        ...     print(client.get("items", 7))
        {'o:id': 7}
        """
        _require_positive(id, "ID")
        return self._http.read(
            self._endpoint(resource, id),
            resource,
            lambda response, _: _listing.record_from(response, "GET", resource),
        )

    def _read_page(self, url: httpx2.URL, resource: str) -> _listing.ListingPage:
        return self._http.read(
            url, resource, lambda response, target: _listing.parse_page(response, target, resource)
        )

    def page(
        self,
        resource: str,
        *,
        filters: QueryParams | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Page:
        """Read one page and report the server's total and next-page status.

        >>> from omeka_s_client.testing import FakeOmeka
        >>> fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}]})
        >>> with OmekaClient("https://example.org", transport=fake) as client:
        ...     print(client.page("items", per_page=1).has_next)
        True
        """
        _require_positive(page, "Page")
        _require_positive(per_page, "Records per page")
        pairs = query_pairs(filters, verify=False)
        url = _page_url(self._endpoint(resource), pairs, page, per_page)
        result = self._read_page(url, resource)
        _listing.check_filters(result.url, pairs, resource)
        if result.next_link is not None:
            self._next_link(result, resource, pairs)
        has_next = result.next_link is not None or (
            result.total is not None
            and (page - 1) * per_page + len(result.records) < result.total
            and bool(result.records)
        )
        return Page(result.records, result.total, page, per_page, has_next)

    def list(
        self,
        resource: str,
        *,
        filters: QueryParams | None = None,
        per_page: int = 50,
        verify: bool = False,
        expected_ids: Iterable[int] | None = None,
        max_records: int | None = None,
    ) -> builtins.list[Record]:
        """Read all pages. An expected ID set always enables verification.

        >>> from omeka_s_client.testing import FakeOmeka
        >>> fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}]})
        >>> with OmekaClient("https://example.org", transport=fake) as client:
        ...     print(len(client.list("items", per_page=1, expected_ids={1, 2})))
        2
        """
        return self._list(
            resource,
            filters=filters,
            per_page=per_page,
            verify=verify,
            expected_ids=expected_ids,
            max_records=max_records,
            order="asc",
        )

    def _list(
        self,
        resource: str,
        *,
        filters: QueryParams | None,
        per_page: int = 50,
        verify: bool = True,
        expected_ids: Iterable[int] | None = None,
        max_records: int | None = None,
        order: str,
    ) -> builtins.list[Record]:
        _require_positive(per_page, "Records per page")
        if max_records is not None:
            _require_positive(max_records, "Maximum records")
        endpoint = self._endpoint(resource)
        verify = verify or expected_ids is not None
        expected = None
        if expected_ids is not None:
            expected = set()
            for id in expected_ids:
                _require_positive(id, "Expected ID")
                expected.add(id)
        pairs = query_pairs(filters, verify=verify)
        if verify:
            pairs.extend([("sort_by", "id"), ("sort_order", order)])
        for _ in range(3):
            try:
                return self._collect(
                    resource, endpoint, pairs, per_page, verify, expected, max_records
                )
            except _listing.VerificationFailure as error:
                reason = str(error)
        raise IncompleteListingError(
            f"GET {resource} failed listing verification after three attempts. {reason}",
            operation="GET",
            resource=resource,
        )

    def _next_link(
        self, page: _listing.ListingPage, resource: str, pairs: builtins.list[tuple[str, str]]
    ) -> httpx2.URL:
        assert page.next_link is not None
        target = self._http.api_target(page.url, page.next_link, resource)
        _listing.check_filters(target, pairs, resource)
        return target

    def _collect(
        self,
        resource: str,
        endpoint: httpx2.URL,
        pairs: builtins.list[tuple[str, str]],
        per_page: int,
        verify: bool,
        expected: set[int] | None,
        max_records: int | None,
    ) -> builtins.list[Record]:
        url = _page_url(endpoint, pairs, 1, per_page)
        visited: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        records: builtins.list[Record] = []
        ids: set[int] = set()
        total = None
        first = True
        while True:
            key = _listing.page_key(url)
            if key in visited:
                raise _loop_error(resource, verify)
            page = self._read_page(url, resource)
            _listing.check_filters(page.url, pairs, resource)
            effective = _listing.page_key(page.url)
            if effective in visited:
                raise _loop_error(resource, verify)
            visited.update((key, effective))
            if first:
                total, first = page.total, False
            elif verify and page.total != total:
                raise _listing.VerificationFailure(
                    f"Count changed from {total} to {page.total} after {len(ids)} unique IDs."
                )
            if max_records is not None and (
                (page.total is not None and page.total > max_records)
                or len(records) + len(page.records) > max_records
            ):
                raise ListingLimitError(
                    f"GET {resource} exceeds the limit of {max_records} records.",
                    operation="GET",
                    resource=resource,
                )
            if verify:
                _listing.verified_ids(page.records, ids, total)
            records.extend(page.records)
            target = self._next_link(page, resource, pairs) if page.next_link is not None else None
            if target is not None and _listing.page_key(target) in visited:
                raise _loop_error(resource, verify)
            if not page.records:
                break
            if target is not None:
                url = target
                continue
            limit = total if verify else page.total
            if limit is None and expected is not None:
                limit = len(expected)
            if limit is None or len(records) >= limit:
                break
            try:
                next_page = int(page.url.params.get("page", "1")) + 1
                size = int(page.url.params.get("per_page", str(per_page)))
                if next_page < 2 or size < 1:
                    raise ValueError
            except ValueError:
                raise InvalidResponseError(
                    "Invalid pagination parameters.", operation="GET", resource=resource
                ) from None
            url = _page_url(endpoint, pairs, next_page, size)
        if verify:
            _listing.verify_end(ids, total, expected)
        return records

    def create(
        self,
        resource: str,
        payload: Mapping[str, Any],
        *,
        files: Upload | Sequence[Upload] | None = None,
    ) -> Record:
        """Create a record with optional files. Use a single Upload for an asset.

        >>> from omeka_s_client.testing import FakeOmeka
        >>> with OmekaClient("https://example.org", transport=FakeOmeka()) as client:
        ...     print(client.create("items", {"o:is_public": True})["o:id"])
        1
        """
        url = self._endpoint(resource)
        indexed = not isinstance(files, Upload)
        uploads = list(files or ()) if indexed else [files]
        _check_upload_indexes(payload, len(uploads))
        if uploads:
            with ExitStack() as stack:
                parts = []
                for index, upload in enumerate(uploads):
                    field = f"file[{index}]" if indexed else "file"
                    parts.append(_file_part(field, upload, stack))
                response = self._http.write(
                    "POST",
                    url,
                    resource,
                    data={"data": json.dumps(dict(payload), ensure_ascii=False, allow_nan=False)},
                    files=parts,
                )
        else:
            response = self._http.write("POST", url, resource, json=dict(payload))
        return _listing.record_from(response, "POST", resource)

    def patch(
        self,
        resource: str,
        id: int,
        payload: Mapping[str, Any],
        *,
        replace_rdf_values: bool = False,
    ) -> Record:
        """Update a record.

        Omeka S treats the RDF values of a record as one field during a patch.
        A payload with RDF values can remove values that the caller omits.

        >>> from omeka_s_client.testing import FakeOmeka
        >>> fake = FakeOmeka({"items": [{"o:id": 1, "o:is_public": True}]})
        >>> with OmekaClient("https://example.org", transport=fake) as client:
        ...     print(client.patch("items", 1, {"o:is_public": False})["o:is_public"])
        False
        """
        _require_positive(id, "ID")
        url = self._endpoint(resource, id)
        if replace_rdf_values is not True and (
            "clear_property_values" in payload
            or any(
                isinstance(value, list) and ":" in key and not key.startswith(("@", "o:", "o-"))
                for key, value in payload.items()
            )
        ):
            raise RDFReplacementRequiredError(
                "PATCH requires replace_rdf_values=True to replace RDF values.",
                operation="PATCH",
                resource=resource,
            )
        response = self._http.write("PATCH", url, resource, json=dict(payload))
        return _listing.record_from(response, "PATCH", resource)

    def download(self, url: str, destination: str | os.PathLike[str]) -> DownloadResult:
        """Stream a file to a new path and return its size and SHA-256 digest.

        >>> from tempfile import TemporaryDirectory
        >>> from omeka_s_client.testing import FakeOmeka
        >>> fake = FakeOmeka(files={"/image.png": b"example"})
        >>> with TemporaryDirectory() as root, OmekaClient(
        ...     "https://example.org", transport=fake
        ... ) as client:
        ...     print(client.download("https://files.example.org/image.png",
        ...                           Path(root) / "image.png").size)
        7
        """
        path = Path(destination)
        if os.path.lexists(path) or not path.parent.is_dir():
            raise DownloadError("Download needs a new destination in an existing directory.")
        temp = None

        def receive(response: httpx2.Response, _: httpx2.URL) -> DownloadResult:
            digest = hashlib.sha256()
            size = 0
            stream.seek(0)
            stream.truncate()
            for chunk in response.iter_bytes():
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
            return DownloadResult(path, size, digest.hexdigest())

        try:
            target = httpx2.URL(url)
            if not http_url(target):
                raise DownloadError("Invalid file URL.")
            fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
            temp = Path(name)
            with os.fdopen(fd, "wb") as stream:
                result = self._http.read(target, None, receive)
            _publish_file(temp, path)
            return result
        except (httpx2.InvalidURL, OSError, ValueError, OmekaError) as error:
            if isinstance(error, DownloadError):
                raise
            raise DownloadError(
                f"File download failed. {error}"
                if isinstance(error, OmekaError)
                else "File download failed.",
                operation="GET",
                status=error.status if isinstance(error, OmekaError) else None,
            ) from None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)


def _page_url(
    endpoint: httpx2.URL, pairs: list[tuple[str, str]], page: int, per_page: int
) -> httpx2.URL:
    return add_query(endpoint, [*pairs, ("page", str(page)), ("per_page", str(per_page))])


def _loop_error(resource: str, verify: bool) -> Exception:
    if verify:
        return _listing.VerificationFailure("A page link repeated.")
    return InvalidResponseError("A page link repeated.", operation="GET", resource=resource)


def _require_positive(value: object, name: str) -> None:
    if not _listing.positive_integer(value):
        raise ConfigurationError(f"{name} must be a positive integer.")


def _check_upload_indexes(payload: Mapping[str, Any], count: int) -> None:
    media = payload.get("o:media")
    records = [payload]
    if isinstance(media, list):
        records.extend(record for record in media if isinstance(record, Mapping))
    for record in records:
        if "file_index" in record:
            index = record["file_index"]
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
                raise ValueError("file_index must refer to a supplied upload.")


def _file_part(field: str, upload: Upload, stack: ExitStack) -> FilePart:
    path = upload.path
    filename = upload.filename or (path.name if path is not None else "upload")
    content_type = upload.content_type or mimetypes.guess_type(filename)[0]
    if path is None:
        assert upload.content is not None
        return field, (filename, upload.content, content_type or "application/octet-stream")
    try:
        stream = stack.enter_context(path.open("rb"))
    except OSError:
        raise ConfigurationError("Cannot open upload file.") from None
    return field, (filename, stream, content_type or "application/octet-stream")


def _publish_file(temp: Path, path: Path) -> None:
    try:
        os.link(temp, path)
    except OSError as error:
        if error.errno not in _NO_LINK:
            raise
        if os.path.lexists(path):
            raise FileExistsError from None
        os.replace(temp, path)
