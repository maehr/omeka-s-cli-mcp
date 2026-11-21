from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from omeka_s_client import (
    ConfigurationError,
    ConnectFailed,
    DownloadError,
    InvalidResponseError,
    OmekaClient,
    OmekaConnectionError,
    OmekaError,
    OmekaHTTPError,
    RDFReplacementRequiredError,
    ResponseLost,
    TransportRequest,
    TransportResponse,
    Upload,
    WriteOutcomeUnknownError,
)


@pytest.mark.parametrize(
    ("failure", "expected", "message"),
    [
        (ConnectFailed, OmekaConnectionError, "not sent"),
        (httpx2.ConnectTimeout, OmekaConnectionError, "not sent"),
        (ResponseLost, WriteOutcomeUnknownError, "unknown"),
        (httpx2.ReadTimeout, WriteOutcomeUnknownError, "unknown"),
    ],
)
def test_write_transport_failure_is_single_send(
    failure: type[Exception],
    expected: type[Exception],
    message: str,
) -> None:
    requests = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        raise failure(request.url)

    with (
        OmekaClient(
            "https://example.org",
            key_identity="key-id",
            key_credential="secret",
            transport=transport,
        ) as client,
        pytest.raises(expected, match=message) as error,
    ):
        client.create("items", {"x-custom": "é"})
    (request,) = requests
    assert request.method == "POST"
    assert json.loads(request.content) == {"x-custom": "é"}
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("status", [302, 400, 500, 503])
def test_write_http_failure_is_single_send(status: int) -> None:
    requests = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return TransportResponse(status, {"Location": "/api/items/1"})

    with (
        OmekaClient("https://example.org", transport=transport) as client,
        pytest.raises(OmekaHTTPError) as error,
    ):
        client.patch("items", 1, {"o:is_public": False})
    (request,) = requests
    assert request.method == "PATCH"
    assert "items/1" in request.url
    assert json.loads(request.content) == {"o:is_public": False}
    assert error.value.status == status


@pytest.mark.parametrize(
    "response", [TransportResponse(204), TransportResponse(200, content=b"OK")]
)
def test_delete_accepts_success_without_parsing_a_record(response: TransportResponse) -> None:
    requests: list[TransportRequest] = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return response

    with OmekaClient(
        "https://example.org/collection/api/",
        key_identity="key-id",
        key_credential="secret",
        transport=transport,
    ) as client:
        assert client.delete("item_sets", 17) is None
    (request,) = requests
    url = urlsplit(request.url)
    assert request.method == "DELETE" and request.content == b""
    assert url.netloc == "example.org" and url.path == "/collection/api/item_sets/17"
    assert parse_qs(url.query) == {"key_identity": ["key-id"], "key_credential": ["secret"]}


@pytest.mark.parametrize("id", [0, -1, True, "17", 1.5, None])
def test_delete_rejects_invalid_targets_before_sending(id: Any) -> None:
    def transport(_: TransportRequest) -> TransportResponse:
        pytest.fail("Invalid deletion sent a request.")

    with OmekaClient("https://example.org", transport=transport) as client:
        with pytest.raises(ConfigurationError, match="positive integer"):
            client.delete("items", id)
        with pytest.raises(ConfigurationError, match="resource name"):
            client.delete("items/17", 17)


@pytest.mark.parametrize(
    ("result", "expected", "status"),
    [
        (TransportResponse(307, {"Location": "/api/items/2"}), OmekaHTTPError, 307),
        (TransportResponse(403), OmekaHTTPError, 403),
        (TransportResponse(404), OmekaHTTPError, 404),
        (TransportResponse(500), OmekaHTTPError, 500),
        (TransportResponse(503), OmekaHTTPError, 503),
        (ConnectFailed, OmekaConnectionError, None),
        (ResponseLost, WriteOutcomeUnknownError, None),
    ],
)
def test_delete_failure_is_single_send(
    result: TransportResponse | type[Exception], expected: type[OmekaError], status: int | None
) -> None:
    requests: list[TransportRequest] = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        if isinstance(result, TransportResponse):
            return result
        raise result(request.url)

    with (
        OmekaClient(
            "https://example.org",
            key_identity="key-id",
            key_credential="secret",
            transport=transport,
        ) as client,
        pytest.raises(expected) as error,
    ):
        client.delete("items", 1)
    (request,) = requests
    assert request.method == "DELETE"
    assert (error.value.operation, error.value.resource, error.value.status) == (
        "DELETE",
        "items",
        status,
    )
    assert "secret" not in str(error.value)


def test_multipart_files_and_payload(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"from disk")
    requests: list[TransportRequest] = []
    result = {"o:id": 1, "x-custom": 42}

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return TransportResponse(201, content=json.dumps(result).encode())

    with OmekaClient("https://example.org", transport=transport) as client:
        record = {"dcterms:title": [{"@value": "à"}], "o:media": [{"file_index": 1}]}
        assert (
            client.create(
                "items",
                record,
                files=[
                    Upload(path=source),
                    Upload(content=b"bytes", filename="second.no-mime"),
                ],
            )
            == result
        )
        assert (
            client.create(
                "assets",
                {},
                files=Upload(
                    content=b"asset",
                    content_type="image/png",
                ),
            )
            == result
        )

    def parts(request: TransportRequest) -> dict[str, Any]:
        mime = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
        message = BytesParser(policy=policy.default).parsebytes(mime + request.content)
        return {
            str(part.get_param("name", header="content-disposition")): (
                part.get_content_type(),
                part.get_filename(),
                part.get_payload(decode=True),
            )
            for part in message.iter_parts()
        }

    payload = parts(requests[0])
    assert payload["data"][2] == json.dumps(record, ensure_ascii=False).encode("utf-8")
    assert payload["file[0]"] == ("text/plain", "source.txt", b"from disk")
    assert payload["file[1]"] == ("application/octet-stream", "second.no-mime", b"bytes")
    assert parts(requests[1])["file"] == ("image/png", "upload", b"asset")


@pytest.mark.parametrize(
    ("payload", "has_file"),
    [
        ({"file_index": 0}, False),
        ({"file_index": 1}, True),
        ({"o:media": [{"file_index": -1}]}, True),
        ({"o:media": [{"file_index": True}]}, True),
        ({"file_index": "0"}, True),
    ],
)
def test_create_checks_file_indexes(payload: dict[str, Any], has_file: bool) -> None:
    def transport(_: TransportRequest) -> TransportResponse:
        pytest.fail("An invalid file_index must fail before send.")

    with (
        OmekaClient("https://example.org", transport=transport) as client,
        pytest.raises(ValueError, match="file_index"),
    ):
        client.create("items", payload, files=Upload(content=b"a") if has_file else None)


def test_upload_source_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Upload()
    with pytest.raises(ValueError):
        Upload(path=tmp_path, content=b"a")
    with (
        OmekaClient("https://example.org", transport=lambda _: pytest.fail("No request")) as client,
        pytest.raises(ConfigurationError, match="Cannot open"),
    ):
        client.create("items", {}, files=Upload(path=tmp_path / "missing"))


def test_patch_preserves_unknown_keys_and_guards_rdf() -> None:
    requests = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(json.loads(request.content))
        return TransportResponse(200, content=request.content)

    rdf = {"dcterms:title": [{"type": "literal", "@language": "de", "@value": "Grüezi"}]}
    module = {
        "o:media": [],
        "@foo:bar": [],
        "o-module-mapping:marker": ["x"],
        "o-cnt:x": [],
        "some:scalar": "value",
    }
    with OmekaClient("https://example.org", transport=transport) as client:
        for payload in (rdf, {"clear_property_values": []}):
            with pytest.raises(RDFReplacementRequiredError):
                client.patch("items", 1, payload)
        assert not requests
        assert client.patch("items", 1, module) == module
        assert client.patch("items", 1, rdf, replace_rdf_values=True) == rdf
    assert requests == [module, rdf]


@pytest.mark.parametrize("status,body", [(201, b"[]"), (204, b"")])
def test_create_requires_object_response(status: int, body: bytes) -> None:
    with (
        OmekaClient(
            "https://example.org", transport=lambda _: TransportResponse(status, content=body)
        ) as client,
        pytest.raises(InvalidResponseError),
    ):
        client.create("items", {})


def _broken_stream() -> Iterator[bytes]:
    yield b"stale prefix that is too long"
    raise ResponseLost("transient")


def test_download_strips_keys_and_restarts_stream(tmp_path: Path) -> None:
    requests = []
    waits = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request.url)
        if len(requests) % 2:
            return TransportResponse(
                308, {"Location": "https://cdn.example.org/file?key_credential=x"}
            )
        chunks = _broken_stream() if len(requests) == 2 else (b"abc", b"123")
        return TransportResponse(200, content=chunks)

    target = tmp_path / "image"
    with OmekaClient(
        "https://example.org",
        key_identity="id",
        key_credential="secret",
        transport=transport,
        sleep=waits.append,
    ) as client:
        result = client.download(
            "https://files.example.org/file?%6Bey_identity=old&keep=%2F%20&key_credential%5B0%5D=bad",
            target,
        )
    assert (
        requests
        == [
            "https://files.example.org/file?keep=%2F%20",
            "https://cdn.example.org/file",
        ]
        * 2
    )
    assert waits == [1]
    assert result.path == target and result.size == 6
    assert target.read_bytes() == b"abc123"
    assert result.sha256 == hashlib.sha256(b"abc123").hexdigest()
    assert list(tmp_path.iterdir()) == [target]
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "reply",
    [
        TransportResponse(200),
        TransportResponse(404),
        TransportResponse(302, {"Location": "file:///etc/hosts"}),
        TransportResponse(302, {"Location": "http://example.org:bad/file"}),
        TransportResponse(301, {"Location": "/file"}),
    ],
)
def test_download_failures_clean_up(reply: TransportResponse, tmp_path: Path) -> None:
    def transport(_: TransportRequest) -> TransportResponse:
        return TransportResponse(200, content=_broken_stream()) if reply.status == 200 else reply

    with (
        OmekaClient("https://example.org", transport=transport, max_retries=0) as client,
        pytest.raises(DownloadError) as error,
    ):
        client.download("https://cdn.example.org/file", tmp_path / "never-written")
    assert list(tmp_path.iterdir()) == []
    assert error.value.status == (404 if reply.status == 404 else None)


@pytest.mark.parametrize("url", ["ftp://example.org/file", "http://example.org:bad/file"])
def test_download_rejects_invalid_urls(url: str, tmp_path: Path) -> None:
    with (
        OmekaClient("https://example.org", transport=lambda _: pytest.fail("No request")) as client,
        pytest.raises(DownloadError),
    ):
        client.download(url, tmp_path / "f")


def test_download_refuses_existing_and_missing_parent(tmp_path: Path) -> None:
    destination = tmp_path / "exists"
    destination.write_text("existing")
    with OmekaClient(
        "https://example.org", transport=lambda _: pytest.fail("No request")
    ) as client:
        for path in (destination, tmp_path / "missing" / "file"):
            with pytest.raises(DownloadError):
                client.download("https://example.org/file", path)
    assert destination.read_text() == "existing"


@pytest.mark.parametrize("disable_links", [True, False])
@pytest.mark.parametrize("race", [True, False])
def test_download_publication(
    disable_links: bool,
    race: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dest = tmp_path / "new"

    def transport(_: TransportRequest) -> TransportResponse:
        if race:
            dest.write_bytes(b"another writer")
        return TransportResponse(200, content=b"network")

    if disable_links:

        def no_links(*_: Any) -> None:
            raise OSError(errno.ENOTSUP, "Hard links unavailable.")

        monkeypatch.setattr(os, "link", no_links)

    with OmekaClient("https://example.org", transport=transport) as client:
        if race:
            with pytest.raises(DownloadError):
                client.download("https://example.org/file", dest)
        else:
            assert client.download("https://example.org/file", dest).size == 7
    assert dest.read_bytes() == (b"another writer" if race else b"network")
    assert list(tmp_path.iterdir()) == [dest]


def test_invalid_write_target_exception_is_sanitized() -> None:
    def transport(request: TransportRequest) -> TransportResponse:
        raise httpx2.InvalidURL(request.url)

    with (
        OmekaClient(
            "https://example.org", transport=transport, key_identity="id", key_credential="private"
        ) as client,
        pytest.raises(InvalidResponseError) as error,
    ):
        client.patch("items", 1, {})
    assert "private" not in str(error.value)
