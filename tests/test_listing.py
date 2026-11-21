from __future__ import annotations

import json
from collections import deque
from urllib.parse import parse_qsl, urlsplit

import pytest

from omeka_s_client import (
    ConfigurationError,
    IncompleteListingError,
    InvalidResponseError,
    ListingLimitError,
    OmekaClient,
    OmekaHTTPError,
    TransportRequest,
    TransportResponse,
    UnsafeRedirectError,
    property_filter,
    property_filters,
)
from omeka_s_client.testing import FakeOmeka


def page(ids: list[int], total: int | None = None, link: str | None = None) -> TransportResponse:
    headers = {}
    if total is not None:
        headers["Omeka-S-Total-Results"] = str(total)
    if link is not None:
        headers["Link"] = link
    return TransportResponse(200, headers, json.dumps([{"o:id": id} for id in ids]).encode())


def test_links_preserve_order_filters_and_replace_keys() -> None:
    requests: list[TransportRequest] = []
    base = "https://example.org/collections/api/items"
    filters = [("property[0][property]", "10"), ("tag", "one"), ("extra", ""), ("tag", "two")]
    link_filters = "tag=two&extra=&property%5B0%5D%5Bproperty%5D=10&tag=one"
    pages = deque(
        [
            page(
                [1],
                3,
                f'<?{link_filters}&page=2&key_identity=old&key_credential=secret>; rel="next"',
            ),
            page([2], 3, f'<{base}?page=3&{link_filters}>; title="a, b"; rel="alternate next"'),
            page([3], 3),
        ]
    )

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return pages.popleft()

    with OmekaClient(
        base.rsplit("/api/", 1)[0],
        key_identity="own-id",
        key_credential="own-key",
        transport=transport,
    ) as client:
        assert client.list("items", filters=filters, per_page=1) == [
            {"o:id": 1},
            {"o:id": 2},
            {"o:id": 3},
        ]
    assert parse_qsl(urlsplit(requests[0].url).query, keep_blank_values=True)[:4] == filters
    for request in requests:
        assert urlsplit(request.url).path == "/collections/api/items"
        assert request.url.endswith("key_identity=own-id&key_credential=own-key")
        assert "secret" not in request.url
    assert not pages


@pytest.mark.parametrize("verify", [True, False])
def test_fallback_page_numbers(verify: bool) -> None:
    sequence = deque([page([1], 2), page([2], 2)])
    requests = []

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(dict(parse_qsl(urlsplit(request.url).query)))
        return sequence.popleft()

    with OmekaClient("https://example.org", transport=transport) as client:
        assert client.list("items", filters={"foo": [True, None]}, per_page=1, verify=verify) == [
            {"o:id": 1},
            {"o:id": 2},
        ]
    assert [p["page"] for p in requests] == ["1", "2"]
    assert [(p.get("sort_by"), p.get("sort_order")) for p in requests] == (
        [("id", "asc")] * 2 if verify else [(None, None)] * 2
    )


def test_page_is_bounded_and_reports_count() -> None:
    fake = FakeOmeka({"items": [{"o:id": i} for i in range(1, 5)]})
    with OmekaClient("https://example.org", transport=fake) as client:
        first = client.page("items", per_page=2)
        last = client.page("items", page=2, per_page=2)
    assert first.records == [{"o:id": 1}, {"o:id": 2}]
    assert (first.total, first.page, first.per_page, first.has_next) == (4, 1, 2, True)
    assert not last.has_next
    assert len(fake.requests) == 2


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("https://other.org/api/items?foo=1&page=2", UnsafeRedirectError),
        ("?bar=1&page=2", InvalidResponseError),
        ("?foo=1&foo=1&page=2", InvalidResponseError),
        ("?foo=1&page=1&per_page=1", InvalidResponseError),
        ("?foo=1&page=2&sort_by_default=random", InvalidResponseError),
    ],
)
def test_untrusted_next_links(target: str, error: type[Exception]) -> None:
    with (
        OmekaClient(
            "https://example.org", transport=lambda _: page([1], 2, f'<{target}>; rel="next"')
        ) as client,
        pytest.raises(error),
    ):
        client.list("items", filters={"foo": 1}, per_page=1)


def test_core_default_sort_parameters_are_accepted() -> None:
    replies = deque(
        [
            page(
                [1],
                2,
                "<?page=2&sort_by=id&sort_order=asc&sort_by_default=&sort_order_default=>; "
                'rel="next"',
            ),
            page([2], 2),
        ]
    )
    with OmekaClient("https://example.org", transport=lambda _: replies.popleft()) as client:
        assert len(client.list("items")) == 2


def test_failed_page_does_not_return_partial_results() -> None:
    replies = deque([page([1], 2), TransportResponse(503), TransportResponse(503)])
    with (
        OmekaClient(
            "https://example.org",
            transport=lambda _: replies.popleft(),
            max_retries=1,
            sleep=lambda _: None,
        ) as client,
        pytest.raises(OmekaHTTPError, match="503"),
    ):
        client.list("items", per_page=1, verify=True)
    assert not replies


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([page([1])], "No count"),
        ([page([1, 1], 2)], "Duplicate IDs"),
        ([page([1], 2), page([1], 2)], "Duplicate IDs"),
        ([page([1], 2), page([2], 3)], "Count changed"),
        ([page([1], 2), page([2])], "Count changed"),
        ([page([1], 2), page([], 2)], "expected count 2"),
        ([page([1], 0)], "expected count 0"),
        ([page([1], 2, "<?page=1&per_page=1&sort_by=id&sort_order=asc>; rel=next")], "repeated"),
        ([TransportResponse(200, {"Omeka-S-Total-Results": "1"}, b"[{}]")], "Invalid record ID"),
    ],
)
def test_verified_listing_restarts(pages: list[TransportResponse], message: str) -> None:
    sequence = deque(pages * 3)
    with (
        OmekaClient("https://example.org", transport=lambda _: sequence.popleft()) as client,
        pytest.raises(IncompleteListingError, match=message),
    ):
        client.list("items", per_page=1, verify=True)
    assert not sequence


def test_verification_can_recover() -> None:
    sequence = deque([page([1, 1], 2), page([1, 2], 2)])
    with OmekaClient("https://example.org", transport=lambda _: sequence.popleft()) as client:
        assert len(client.list("items", verify=True)) == 2
    assert not sequence


def test_expected_ids_enable_verification_without_count() -> None:
    responses = deque([page([5]), page([8])])
    with OmekaClient("https://example.org", transport=lambda _: responses.popleft()) as client:
        assert client.list("items", per_page=1, expected_ids=iter([8, 5])) == [
            {"o:id": 5},
            {"o:id": 8},
        ]


def test_expected_ids_must_match_even_when_counts_match() -> None:
    response = page(list(range(100, 113)), 13)
    with (
        OmekaClient("https://example.org", transport=lambda _: response) as client,
        pytest.raises(IncompleteListingError, match="Missing examples") as error,
    ):
        client.list("items", expected_ids=range(1, 14))
    assert "1, 2, 3, 4, 5, 6, 7, 8, 9, 10]" in str(error.value)
    assert "Unexpected examples: []" in str(error.value)


@pytest.mark.parametrize(
    ("verify", "key"),
    [
        (False, "page"),
        (False, "per_page"),
        (False, "key_identity"),
        (False, "key_credential"),
        (False, "key.credential"),
        (False, "key_credential[0]"),
        (True, "sort_order"),
        (True, "sort_by"),
    ],
)
def test_reserved_filters(verify: bool, key: str) -> None:
    fake = FakeOmeka()
    with (
        OmekaClient("https://example.org", transport=fake) as client,
        pytest.raises(ConfigurationError, match="reserved"),
    ):
        client.list("items", filters={key: "1"}, verify=verify)
    assert not fake.requests


@pytest.mark.parametrize(
    "reply",
    [
        TransportResponse(200, content=b"{}"),
        TransportResponse(200, content=b"[1]"),
        TransportResponse(200, {"Omeka-S-Total-Results": "-1"}, b"[]"),
        TransportResponse(200, {"Omeka-S-Total-Results": "abc"}, b"[]"),
        page([], 0, '<>; rel="next"'),
        page([], 0, "<?page=2>; rel=next, <?page=3>; rel=next"),
    ],
)
def test_invalid_page(reply: TransportResponse) -> None:
    with (
        OmekaClient("https://example.org", transport=lambda _: reply) as client,
        pytest.raises(InvalidResponseError),
    ):
        client.page("items")


@pytest.mark.parametrize("count", [None, 1000])
def test_bounded_listing_count_or_body(count: int | None) -> None:
    with OmekaClient("https://example.org", transport=lambda _: page([1, 2], count)) as client:
        with pytest.raises(ListingLimitError):
            client.list("items", max_records=1)
        with pytest.raises(ConfigurationError):
            client.list("items", max_records=0)


def test_property_filters() -> None:
    assert property_filters(
        property_filter("dcterms:identifier", "eq", "a,b"),
        property_filter(10, "nex", "ignored", joiner="or"),
        property_filter(2, "dt", 4),
        property_filter("dcterms:title", "lex", "à", joiner="and"),
    ) == [
        ("property[0][property]", "dcterms:identifier"),
        ("property[0][type]", "eq"),
        ("property[0][text]", "a,b"),
        ("property[1][property]", "10"),
        ("property[1][type]", "nex"),
        ("property[1][joiner]", "or"),
        ("property[2][property]", "2"),
        ("property[2][type]", "dt"),
        ("property[2][text]", "4"),
        ("property[3][property]", "dcterms:title"),
        ("property[3][type]", "lex"),
        ("property[3][text]", "à"),
        ("property[3][joiner]", "and"),
    ]


@pytest.mark.parametrize(
    ("next_page", "size"),
    [
        ("word", "5"),
        ("2", "0"),
        ("0", "5"),
        ("2", "word"),
    ],
)
def test_invalid_fallback_input(next_page: str, size: str) -> None:
    responses = deque(
        [
            page([1], 3, f"<?page={next_page}&per_page={size}>; rel=next"),
            page([2], 3),
        ]
    )
    with (
        OmekaClient("https://example.org", transport=lambda _: responses.popleft()) as client,
        pytest.raises(InvalidResponseError, match="pagination parameters"),
    ):
        client.list("items")


@pytest.mark.parametrize("redirect", [False, True])
def test_repeated_pages_after_fallback_or_redirect(redirect: bool) -> None:
    responses = deque(
        [
            page([1], 6, "<?page=3&per_page=1>; rel=next, <?page=6&per_page=1>; rel=last"),
            page([2], 6, "<?page=2&per_page=1>; rel=next"),
            TransportResponse(302, {"Location": "?page=3&per_page=1"})
            if redirect
            else page([3], 6),
        ]
    )
    if redirect:
        responses.append(page([2], 6))
    with (
        OmekaClient("https://example.org", transport=lambda _: responses.popleft()) as client,
        pytest.raises(InvalidResponseError, match="repeated"),
    ):
        client.list("items", per_page=1)
    assert not responses
