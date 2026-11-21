from __future__ import annotations

import pytest

from omeka_s_client import TransportRequest
from omeka_s_client.testing import FakeOmeka


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("GET", "/bad", b"", 404),
        ("GET", "/api/bad", b"", 404),
        ("GET", "/api/items/9", b"", 404),
        ("GET", "/api/items/2", b"", 200),
        ("GET", "/api/items", b"", 200),
        ("PUT", "/api/items", b"", 405),
        ("DELETE", "/api/items/9", b"", 404),
        ("PUT", "/api/items/2", b"", 404),
        ("POST", "/api/items", b"[]", 400),
        ("PATCH", "/api/items/2", b"", 400),
    ],
)
def test_fake_errors_when_route_or_input_does_not_match(
    method: str,
    path: str,
    body: bytes,
    status: int,
) -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}]})
    request = TransportRequest(
        method,
        "https://example.org" + path,
        {"content-type": "application/json"} if body else {},
        body,
    )
    assert fake(request).status == status


def test_fake_delete_removes_only_the_target_record() -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}], "item_sets": [{"o:id": 2}]})
    request = TransportRequest("DELETE", "https://example.org/api/items/2")
    response = fake(request)
    assert response.status == 204 and response.content == b""
    assert fake(request).status == 404
    assert fake.records == {"items": [{"o:id": 1}], "item_sets": [{"o:id": 2}]}
