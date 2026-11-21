from __future__ import annotations

import logging
import traceback
from collections import deque
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from omeka_s_client import (
    ConfigurationError,
    ConnectFailed,
    InvalidResponseError,
    OmekaClient,
    OmekaConnectionError,
    OmekaHTTPError,
    ResponseLost,
    TransportRequest,
    TransportResponse,
    UnsafeRedirectError,
)
from omeka_s_client.testing import FakeOmeka


@pytest.mark.parametrize(
    ("supplied", "normalized"),
    [
        ("https://example.org", "https://example.org"),
        ("https://example.org/api", "https://example.org"),
        ("https://example.org/api/", "https://example.org"),
        ("https://example.org/collection/", "https://example.org/collection"),
        ("https://example.org/collection/api/", "https://example.org/collection"),
        ("https://EXAMPLE.org:443/api/", "https://example.org"),
        ("http://EXAMPLE.org:80/collection/api/", "http://example.org/collection"),
        ("https://EXAMPLE.org:8443/site/api/", "https://example.org:8443/site"),
    ],
)
def test_installation_url(supplied: str, normalized: str) -> None:
    with OmekaClient(supplied) as client:
        assert client.installation_url == normalized
        assert client.api_url == normalized + "/api/"


@pytest.mark.parametrize(
    "invalid",
    [
        "ftp://example.org",
        "/installation",
        "https:///api",
        "https://user:secret@example.org",
        "https://@example.org",
        "https://example.org?token=secret",
        "https://example.org?",
        "https://example.org/#fragment",
        "https://example.org/#",
        "https://example.org:bad",
        "https://example.org/%2e%2e/install",
        "https://example.org/path%2finstall",
        None,
    ],
)
def test_invalid_installations(invalid: Any) -> None:
    with pytest.raises(ConfigurationError) as error:
        OmekaClient(invalid)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "options",
    [
        {"key_identity": "identity"},
        {"key_credential": "credential"},
        {"key_identity": "", "key_credential": "credential"},
        {"key_identity": "identity", "key_credential": " "},
        {"key_identity": "identity", "key_credential": ""},
        {"timeout": None},
        {"timeout": False},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"timeout": "1"},
        {"max_retries": -1},
        {"max_retries": True},
        {"max_retries": 1.5},
    ],
)
def test_invalid_configuration(options: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        OmekaClient("https://example.org", **options)


def test_request_headers_and_authentication() -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}]})

    options: tuple[dict[str, Any], ...] = (
        {},
        {"key_identity": "test ID", "key_credential": "space & secret"},
    )
    for keys in options:
        with OmekaClient("https://example.org/collection/api", transport=fake, **keys) as client:
            assert client.get("items", 1) == {"o:id": 1}
        request = fake.requests[-1]
        parsed = urlsplit(request.url)
        assert parsed.path == "/collection/api/items/1"
        assert parse_qs(parsed.query) == {key: [value] for key, value in keys.items()}
        assert request.headers["user-agent"].startswith("omeka-s-client/")
        assert request.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "target",
    [
        "https://other.org/collection/api/items/1",
        "http://example.org/collection/api/items/1",
        "https://example.org:444/collection/api/items/1",
        "/collection/apix/items/1",
        "/collection/api",
        "/collection/api/%2E%2e/private",
        "/collection/api/%252fprivate",
        "/collection/api/%5cprivate",
        "https://user@example.org/collection/api/items/1",
        "https://example.org:bad/collection/api/items/1",
    ],
)
def test_redirects_cannot_leave_api_root(target: str) -> None:
    requests = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return TransportResponse(302, {"Location": target + "?key_credential=foreign-secret"})

    with (
        OmekaClient(
            "https://example.org/collection",
            transport=transport,
            key_identity="test-identity",
            key_credential="test-credential",
        ) as client,
        pytest.raises(UnsafeRedirectError) as error,
    ):
        client.get("items", 1)
    assert len(requests) == 1
    assert "secret" not in str(error.value)
    assert "test-credential" not in str(error.value)


def test_safe_redirect_replaces_keys_and_logs_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[TransportRequest] = []
    target = (
        "https://EXAMPLE.org:443/collection/api/items/1?"
        "x=visible&%6Bey%5Fcredential=foreign-secret&key.identity=foreign-identity"
    )

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        if len(requests) == 1:
            logging.getLogger("httpcore2").debug("Target %s", target)
            return TransportResponse(303, {"Location": target})
        return TransportResponse(200, content=b'{"o:id":1}')

    with (
        caplog.at_level(logging.DEBUG),
        OmekaClient(
            "https://example.org/collection",
            transport=transport,
            key_identity="local-identity",
            key_credential="local-secret",
        ) as client,
    ):
        assert client.get("items", 1) == {"o:id": 1}

    assert len(requests) == 2
    assert parse_qs(urlsplit(requests[-1].url).query) == {
        "x": ["visible"],
        "key_identity": ["local-identity"],
        "key_credential": ["local-secret"],
    }
    assert "visible" in caplog.text
    assert not any(
        secret in caplog.text
        for secret in ("local-secret", "foreign-secret", "local-identity", "foreign-identity")
    )


def test_redirect_limit() -> None:
    fake = []

    def transport(request: TransportRequest) -> TransportResponse:
        fake.append(request)
        return TransportResponse(301, {"Location": "1"})

    with (
        OmekaClient("https://example.org", transport=transport) as client,
        pytest.raises(UnsafeRedirectError, match="five"),
    ):
        client.get("items", 1)
    assert len(fake) == 6


@pytest.mark.parametrize("failure", [ConnectFailed, ResponseLost, httpx2.ReadTimeout])
def test_exhausted_connection_error_is_sanitized(failure: type[Exception]) -> None:
    pauses = []

    def transport(request: TransportRequest) -> TransportResponse:
        raise failure(request.url)

    with (
        OmekaClient(
            "https://example.org",
            key_identity="id",
            key_credential="very-secret",
            transport=transport,
            sleep=pauses.append,
        ) as client,
        pytest.raises(OmekaConnectionError) as error,
    ):
        client.get("items", 1)
    assert pauses == [1, 2, 4]
    assert error.value.operation == "GET" and error.value.resource == "items"
    assert error.value.__suppress_context__
    rendered = "".join(traceback.format_exception(error.value))
    assert "very-secret" not in rendered


@pytest.mark.parametrize(
    ("status", "retry_after", "delay"),
    [
        (429, "35", 30),
        (502, "nonsense", 1),
        (503, None, 1),
        (504, "-3", 0),
        (429, format_datetime(datetime.now(UTC) + timedelta(minutes=5)), 30),
    ],
)
def test_get_retries_temporary_statuses(status: int, retry_after: str | None, delay: float) -> None:
    waits = []
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    responses = deque([TransportResponse(status, headers), TransportResponse(200, content=b"{}")])
    with OmekaClient(
        "https://example.org", transport=lambda _: responses.popleft(), sleep=waits.append
    ) as client:
        assert client.get("items", 1) == {}
    assert waits == [delay] and not responses


@pytest.mark.parametrize("status", [301, 401, 404, 500, 503])
def test_http_error_does_not_return_body(status: int) -> None:
    pauses = []
    with (
        OmekaClient(
            "https://example.org",
            transport=lambda _: TransportResponse(status, content=b"secret"),
            sleep=pauses.append,
        ) as client,
        pytest.raises(OmekaHTTPError) as error,
    ):
        client.get("items", 1)
    assert error.value.status == status
    assert "secret" not in str(error.value)
    assert pauses == ([1, 2, 4] if status == 503 else [])


@pytest.mark.parametrize("content", [b"garbage", b"[]", b"null", b'{"x": NaN}'])
def test_get_rejects_an_invalid_record(content: bytes) -> None:
    with (
        OmekaClient(
            "https://example.org",
            transport=lambda _: TransportResponse(200, content=content),
        ) as client,
        pytest.raises(InvalidResponseError),
    ):
        client.get("items", 1)


@pytest.mark.parametrize("name", ["../users", "items/1", "items?foo", "items%20", ""])
def test_resource_guard(name: str) -> None:
    fake = FakeOmeka()
    with OmekaClient("https://example.org", transport=fake) as client:
        with pytest.raises(ConfigurationError):
            client.get(name, 1)
        with pytest.raises(ConfigurationError):
            client.list(name)
        with pytest.raises(ConfigurationError):
            client.create(name, {})
    assert not fake.requests


@pytest.mark.parametrize("id", [True, False, -1, 0, 1.0, "1"])
def test_id_guard(id: Any) -> None:
    fake = FakeOmeka()
    with OmekaClient("https://example.org", transport=fake) as client:
        with pytest.raises(ConfigurationError):
            client.get("items", id)
        with pytest.raises(ConfigurationError):
            client.patch("items", id, {})
        with pytest.raises(ConfigurationError):
            client.list("items", expected_ids=[id])
    assert not fake.requests


def test_log_filter_clears_credential_bearing_exception(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("httpcore2.http11")
    with caplog.at_level(logging.DEBUG), OmekaClient("https://example.org"):
        try:
            raise ValueError("https://example.org/?key_identity=my-secret")
        except ValueError:
            logger.exception("An HTTP exception.")
    assert "HTTP exception" in caplog.text and "my-secret" not in caplog.text


def test_private_client_refuses_direct_out_of_root_read() -> None:
    with (
        OmekaClient("https://example.org", transport=lambda _: pytest.fail("No request")) as client,
        pytest.raises(UnsafeRedirectError),
    ):
        client._http.read(httpx2.URL("https://other.org/api/items"), "items", lambda *_: None)


def test_strip_keys_preserves_non_utf8_query_names() -> None:
    from unittest.mock import Mock

    from omeka_s_client._urls import without_keys

    url = Mock(spec=httpx2.URL, query=b"legacy-\xff=value&key_credential=old&keep=%2f")
    assert without_keys(url) is url.copy_with.return_value
    url.copy_with.assert_called_once_with(query=b"legacy-\xff=value&keep=%2f")
