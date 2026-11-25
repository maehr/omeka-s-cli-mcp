from __future__ import annotations

import pytest

from omeka_s_client import (
    IncompleteListingError,
    OmekaClient,
    TransportRequest,
    Upload,
    property_filter,
    property_filters,
)
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


def test_fake_api_resources_ignore_paging_like_omeka() -> None:
    fake = FakeOmeka({f"resource_{index:02}": [] for index in range(60)})
    with OmekaClient("https://example.org", transport=fake) as client:
        page = client.page("api_resources", per_page=1)
        assert len(page.records) == 60
        assert page.total is None
        assert not page.has_next
        assert len(client.list("api_resources")) == 60


def test_verified_api_resources_listing_fails_without_count_or_integer_ids() -> None:
    fake = FakeOmeka({"items": []})
    with (
        OmekaClient("https://example.org", transport=fake, sleep=lambda _: None) as client,
        pytest.raises(IncompleteListingError),
    ):
        client.list("api_resources", verify=True)


def test_fake_delete_removes_only_the_target_record() -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}], "item_sets": [{"o:id": 2}]})
    request = TransportRequest("DELETE", "https://example.org/api/items/2")
    response = fake(request)
    assert response.status == 204 and response.content == b""
    assert fake(request).status == 404
    assert fake.records == {"items": [{"o:id": 1}], "item_sets": [{"o:id": 2}]}


def test_fake_creates_records_from_multipart_uploads() -> None:
    fake = FakeOmeka({"items": [{"o:id": 7}]})
    item = {
        "dcterms:title": [{"@value": "Grüezi"}],
        "o:media": [{"o:ingester": "upload", "file_index": 0}],
    }
    asset = {"o:name": "Example asset"}
    upload = Upload(content=b"\x00\xff", filename="example.png")
    with OmekaClient("https://example.org", transport=fake) as client:
        assert client.create("items", item, files=[upload]) == {**item, "o:id": 8}
        assert client.create("assets", asset, files=upload) == {**asset, "o:id": 1}
        assert client.get("items", 8) == {**item, "o:id": 8}
        assert client.get("assets", 1) == {**asset, "o:id": 1}
    assert list(fake.records) == ["items", "assets"]
    assert not fake.files


@pytest.mark.parametrize(
    ("content_type", "parts"),
    [
        ("multipart/form-data", []),
        ("multipart/form-data; boundary=test", [b'form-data; name="file"\r\n\r\n{}']),
        ("multipart/form-data; boundary=test", [b'form-data; name="data"\r\n\r\n{}'] * 2),
        ("multipart/form-data; boundary=test", [b'form-data; name="data"\r\n\r\ninvalid']),
        ("multipart/form-data; boundary=test", [b'form-data; name="data"\r\n\r\n[]']),
        (
            "multipart/form-data; boundary=test",
            [b'form-data; name="data"; filename="data.json"\r\n\r\n{}'],
        ),
        (
            "multipart/form-data; boundary=test",
            [
                b'form-data; name="data"\r\nContent-Type: multipart/mixed; boundary=inner\r\n'
                b"\r\n--inner\r\n\r\n{}\r\n--inner--"
            ],
        ),
        ("multipart/form-data; boundary=test", [b'attachment; name="data"\r\n\r\n{}']),
    ],
)
def test_fake_rejects_invalid_multipart_creation(content_type: str, parts: list[bytes]) -> None:
    body = b"".join(b"--test\r\nContent-Disposition: " + part + b"\r\n" for part in parts)
    fake = FakeOmeka()
    response = fake(
        TransportRequest(
            "POST",
            "https://example.org/api/items",
            {"content-type": content_type},
            body + b"--test--\r\n",
        )
    )
    assert response.status == 400
    assert not fake.records


def test_fake_exact_match_uses_the_supplied_term_and_value() -> None:
    uri = "https://example.org/uri?q=a+b&c=d"
    fake = FakeOmeka(
        {
            "items": [
                {"o:id": 1, "dcterms:title": [{"@value": "ABC"}, {"@value": "abc"}]},
                {"o:id": 2, "schema:identifier": [None, {"@value": "abc"}]},
                {"o:id": 3, "dcterms:title": [{"@value": "ABC"}]},
                {"o:id": 4, "schema:identifier": "abc"},
                {"o:id": 5, "schema:url": [{"type": "uri", "@id": uri}]},
                {"o:id": 6, "schema:url": [{"type": "resource", "@id": uri}]},
            ]
        }
    )
    with OmekaClient("https://example.org", transport=fake) as client:
        for term, text, ids in (
            ("dcterms:title", "abc", [1]),
            ("schema:identifier", "abc", [2]),
            ("dcterms:title", "ab", []),
            ("custom:missing", "abc", []),
            ("schema:url", uri, [5]),
        ):
            records = client.list(
                "items", filters=property_filters(property_filter(term, "eq", text))
            )
            assert [record["o:id"] for record in records] == ids


def test_fake_exact_match_combines_property_clauses() -> None:
    alpha = {"custom:code": [{"@value": "alpha"}]}
    beta = {"custom:code": [{"@value": "beta"}]}
    active = {"schema:status": [{"@value": "active"}]}
    fake = FakeOmeka(
        {"items": [{"o:id": 1, **alpha}, {"o:id": 2, **beta}, {"o:id": 3, **beta, **active}]}
    )
    conditions = property_filters(
        property_filter("custom:code", "eq", "alpha"),
        property_filter("custom:code", "eq", "beta", joiner="or"),
        property_filter("schema:status", "eq", "active", joiner="and"),
    )
    with OmekaClient("https://example.org", transport=fake) as client:
        assert [record["o:id"] for record in client.list("items", filters=conditions)] == [1, 3]


def test_fake_ignores_unsupported_or_incomplete_property_clauses() -> None:
    record = {"o:id": 1, "custom:code": [{"property_id": 10, "@value": "abc"}]}
    filters = property_filters(
        property_filter("custom:code", "ex"),
        property_filter(10, "eq", "nonmatch"),
        property_filter("", "eq", "nonmatch"),
        property_filter("custom:code", "eq"),
    )
    with OmekaClient("https://example.org", transport=FakeOmeka({"items": [record]})) as client:
        assert client.list("items", filters=filters) == [record]


@pytest.mark.parametrize(
    ("resource", "filter_key", "relation", "reference"),
    [
        ("items", "item_set_id", "o:item_set", [{"o:id": 7}]),
        ("media", "item_id", "o:item", {"o:id": 7}),
    ],
)
def test_fake_paginates_exact_matches_with_relationship_filter(
    resource: str, filter_key: str, relation: str, reference: object
) -> None:
    match = {"custom:code": [{"@value": "abc"}]}
    fake = FakeOmeka(
        {
            resource: [
                {"o:id": 4, relation: reference, **match},
                {"o:id": 3, **match},
                {"o:id": 2, relation: reference},
                {"o:id": 1, relation: reference, **match},
            ]
        }
    )
    filters = [(filter_key, "7"), *property_filters(property_filter("custom:code", "eq", "abc"))]
    with OmekaClient("https://example.org", transport=fake) as client:
        desc = [*filters, ("sort_order", "desc")]
        first = client.page(resource, filters=desc, per_page=1)
        second = client.page(resource, filters=desc, page=2, per_page=1)
        assert first.total == second.total == 2
        assert first.has_next and not second.has_next
        assert first.records[0]["o:id"] == 4 and second.records[0]["o:id"] == 1
        records = client.list(resource, filters=filters, per_page=1, expected_ids={1, 4})
        assert [record["o:id"] for record in records] == [1, 4]
