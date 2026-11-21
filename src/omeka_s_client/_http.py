"""Private HTTPX2 clients and request policy."""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Callable, Generator, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from typing import BinaryIO, TypeVar

import httpx2

from ._urls import NONCE, add_query, http_url, is_key, under_root, without_keys
from .errors import (
    InvalidResponseError,
    OmekaConnectionError,
    OmekaHTTPError,
    UnsafeRedirectError,
    WriteOutcomeUnknownError,
)
from .transport import ConnectFailed, ResponseLost, Transport, TransportRequest
from .types import Record

VERSION = version("omeka-s-client")
TEMPORARY_STATUSES = {429, 502, 503, 504}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_UNSENT = (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout)
_T = TypeVar("_T")
FilePart = tuple[str, tuple[str, BinaryIO | bytes, str]]
_QUERY_PARAMETER = re.compile(r"""([?&])([^=&?\s"'<>#]+)=([^&\s"'<>#]*)""")


def _redact_parameter(match: re.Match[str]) -> str:
    if is_key(match[2]):
        return f"{match[1]}{match[2]}=[redacted]"
    return match[0]


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = _QUERY_PARAMETER.sub(_redact_parameter, message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        if record.exc_info:
            record.exc_info, record.exc_text = None, None
        return True


_REDACT = _Redact()


def _install_log_filters() -> None:
    # Filters on a parent logger do not apply to records from child loggers.
    names = {"httpx2", "httpcore2"}
    names.update(
        name
        for name in logging.root.manager.loggerDict.copy()
        if name.startswith(("httpx2.", "httpcore2."))
    )
    for name in names:
        logging.getLogger(name).addFilter(_REDACT)


class _Stream(httpx2.SyncByteStream):
    def __init__(self, chunks: Iterable[bytes], request: httpx2.Request) -> None:
        self.chunks = chunks
        self.request = request

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.chunks
        except (ConnectFailed, ResponseLost):
            raise httpx2.ReadError("Injected stream failure.", request=self.request) from None


def _adapt(transport: Transport) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        try:
            response = transport(
                TransportRequest(
                    request.method, str(request.url), dict(request.headers), request.read()
                )
            )
        except ConnectFailed:
            raise httpx2.ConnectError("Injected connection failure.", request=request) from None
        except ResponseLost:
            raise httpx2.ReadError("Injected response loss.", request=request) from None
        if isinstance(response.content, bytes):
            return httpx2.Response(
                response.status, headers=response.headers, content=response.content
            )
        return httpx2.Response(
            response.status, headers=response.headers, stream=_Stream(response.content, request)
        )

    return httpx2.MockTransport(handler)


def _delay(value: str | None, attempt: int) -> float:
    if value is not None:
        try:
            return float(min(30, max(0, int(value))))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return min(30.0, max(0.0, (date - datetime.now(UTC)).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
    return float(2 ** min(attempt, 5))


class HTTP:
    def __init__(
        self,
        root: str,
        keys: list[tuple[str, str]],
        timeout: float,
        transport: Transport | None,
        retries: int,
        sleep: Callable[[float], None],
        cache_busting: bool = False,
    ) -> None:
        self._cache_busting = cache_busting
        self.root = httpx2.URL(root)
        self._keys = keys
        self._retries = retries
        self._sleep = sleep
        headers = {"User-Agent": f"omeka-s-client/{VERSION}", "Cache-Control": "no-cache"}
        self._api = httpx2.Client(
            timeout=timeout,
            headers=headers,
            transport=None if transport is None else _adapt(transport),
            follow_redirects=False,
            trust_env=False,
        )
        self._files = httpx2.Client(
            timeout=timeout,
            headers=headers,
            transport=None if transport is None else _adapt(transport),
            follow_redirects=False,
            trust_env=False,
        )

        _install_log_filters()

    def close(self) -> None:
        try:
            self._api.close()
        finally:
            self._files.close()

    def api_target(self, base: httpx2.URL, target: str, resource: str) -> httpx2.URL:
        try:
            url = without_keys(base.join(target)).copy_with(fragment=None)
            if under_root(url, self.root):
                return url
        except (httpx2.InvalidURL, ValueError):
            pass
        raise UnsafeRedirectError(
            "GET target leaves the Omeka API root.", operation="GET", resource=resource
        )

    @contextmanager
    def _open(
        self,
        method: str,
        url: httpx2.URL,
        resource: str | None,
        *,
        json: Record | None = None,
        data: dict[str, str] | None = None,
        files: list[FilePart] | None = None,
    ) -> Generator[tuple[httpx2.Response, httpx2.URL]]:
        api = resource is not None
        client = self._api if api else self._files
        hop = 0
        while True:
            url = without_keys(url)
            if api and not under_root(url, self.root):
                raise UnsafeRedirectError(
                    "Request target leaves the Omeka API root.", operation=method, resource=resource
                )
            bust = self._cache_busting and api and method == "GET"
            pairs = [*self._keys, (NONCE, secrets.token_hex(8))] if bust else self._keys
            outgoing = add_query(url, pairs) if api and pairs else url
            headers = {"Pragma": "no-cache"} if bust else None
            with client.stream(
                method, outgoing, headers=headers, json=json, data=data, files=files
            ) as response:
                location = response.headers.get("location")
                if (
                    method == "GET"
                    and response.status_code in REDIRECT_STATUSES
                    and location is not None
                ):
                    if hop == 5:
                        raise UnsafeRedirectError(
                            "GET exceeded five redirects.", operation=method, resource=resource
                        )
                    if resource is not None:
                        url = self.api_target(url, location, resource)
                    else:
                        url = url.join(location)
                        if not http_url(url):
                            raise UnsafeRedirectError("Invalid file redirect.", operation=method)
                    hop += 1
                    continue
                yield response, url
                return

    def read(
        self,
        url: httpx2.URL,
        resource: str | None,
        receive: Callable[[httpx2.Response, httpx2.URL], _T],
    ) -> _T:
        attempt = 0
        while True:
            try:
                with self._open("GET", url, resource) as (response, effective_url):
                    status = response.status_code
                    if status in TEMPORARY_STATUSES and attempt < self._retries:
                        wait = _delay(response.headers.get("retry-after"), attempt)
                    else:
                        _check_status(status, "GET", resource)
                        return receive(response, effective_url)
            except httpx2.RequestError:
                if attempt == self._retries:
                    raise OmekaConnectionError(
                        "GET failed after read attempts.", operation="GET", resource=resource
                    ) from None
                wait = _delay(None, attempt)
            except httpx2.InvalidURL:
                raise InvalidResponseError(
                    "GET target is invalid.", operation="GET", resource=resource
                ) from None
            self._sleep(wait)
            attempt += 1

    def write(
        self,
        method: str,
        url: httpx2.URL,
        resource: str,
        *,
        json: Record | None = None,
        data: dict[str, str] | None = None,
        files: list[FilePart] | None = None,
    ) -> httpx2.Response:
        try:
            with self._open(method, url, resource, json=json, data=data, files=files) as (
                response,
                _,
            ):
                _check_status(response.status_code, method, resource)
                response.read()
                return response
        except _UNSENT:
            raise OmekaConnectionError(
                f"{method} {resource} was not sent.", operation=method, resource=resource
            ) from None
        except (httpx2.RequestError, OSError):
            raise WriteOutcomeUnknownError(
                f"{method} {resource} outcome is unknown.", operation=method, resource=resource
            ) from None
        except httpx2.InvalidURL:
            raise InvalidResponseError(
                f"{method} {resource} target is invalid.", operation=method, resource=resource
            ) from None


def _check_status(status: int, method: str, resource: str | None) -> None:
    if not 200 <= status < 300:
        raise OmekaHTTPError(
            f"{method} {resource or 'file'} returned HTTP {status}.",
            operation=method,
            resource=resource,
            status=status,
        )
