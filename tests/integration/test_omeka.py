from __future__ import annotations

import base64
import hashlib
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from omeka_s_client import OmekaClient, Upload, capture_snapshot, property_filter, property_filters

pytestmark = pytest.mark.integration

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK3sAAAAASUVORK5CYII="
)


@dataclass
class Instance:
    url: str
    identity: str = field(repr=False)
    credential: str = field(repr=False)
    client: OmekaClient


@pytest.fixture(scope="module")
def instance() -> Iterator[Instance]:
    url = os.getenv("OMEKA_IT_URL")
    if not url:
        pytest.skip("Set OMEKA_IT_URL for disposable instance tests.")
    if urlsplit(url).hostname not in {"127.0.0.1", "::1", "localhost"}:
        pytest.fail("Integration writes require a loopback Omeka URL.")
    identity = os.environ["OMEKA_IT_KEY_IDENTITY"]
    credential = os.environ["OMEKA_IT_KEY_CREDENTIAL"]
    with OmekaClient(
        url, key_identity=identity, key_credential=credential, max_retries=0
    ) as client:
        yield Instance(url, identity, credential, client)


def literal(value: str, property_id: int) -> list[dict[str, str | int]]:
    return [{"type": "literal", "property_id": property_id, "@value": value}]


def test_paginated_snapshot_and_write_semantics(
    instance: Instance,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url, client = instance.url, instance.client
    item_set = client.create(
        "item_sets", {"o:is_public": True, "dcterms:title": literal("Test", 1)}
    )
    ids = []
    for index in range(3):
        payload = {
            "o:is_public": True,
            "o:item_set": [{"o:id": item_set["o:id"]}],
            "dcterms:title": literal(f"Item {index}", 1),
            "dcterms:identifier": literal("duplicate-identifier", 10),
        }
        if index == 0:
            payload["o:media"] = [{"o:ingester": "upload", "file_index": 0}]
        item = client.create(
            "items",
            payload,
            files=[Upload(content=_PNG, filename="image.png")] if index == 0 else None,
        )
        ids.append(item["o:id"])

    filters = {"item_set_id": item_set["o:id"]}
    with OmekaClient(url, max_retries=0) as public:
        assert len(public.page("api_resources").records) > 10
        assert public.page("items", filters=filters, per_page=1).has_next
        assert [
            record["o:id"] for record in public.list("items", filters=filters, per_page=1)
        ] == ids
    with (
        caplog.at_level(logging.DEBUG, logger="httpx2"),
        caplog.at_level(logging.DEBUG, logger="httpcore2"),
    ):
        verified = client.list("items", filters=filters, per_page=1, expected_ids=ids)
    if any(key in caplog.text for key in (instance.identity, instance.credential)):
        caplog.clear()
        pytest.fail("HTTP logs expose an API key.")
    assert "[redacted]" in caplog.text
    assert [record["o:id"] for record in verified] == ids

    with httpx2.Client(trust_env=False) as raw:
        response = raw.get(
            url + "/api/items",
            params={
                **filters,
                "per_page": 1,
                "page": 1,
                "key_identity": instance.identity,
                "key_credential": instance.credential,
            },
        )
        assert response.headers["Omeka-S-Total-Results"] == "3"
        next_url = next(
            link["url"] for link in response.links.values() if link.get("rel") == "next"
        )
        assert urlsplit(next_url).scheme == "http"
        query = parse_qs(urlsplit(next_url).query, keep_blank_values=True)
        if query.pop("key_identity", []) != [instance.identity] or query.pop(
            "key_credential", []
        ) != [instance.credential]:
            pytest.fail("Expected both keys in the next link.")
        if os.getenv("OMEKA_VERSION") in {"4.1.1", "4.2.1"}:
            assert query.pop("sort_by_default") == [""]
            assert query.pop("sort_order_default") == [""]
        else:
            for name in ("sort_by_default", "sort_order_default"):
                if name in query:
                    assert query.pop(name) == [""]
        assert query == {
            "page": ["2"],
            "per_page": ["1"],
            "sort_by": ["id"],
            "sort_order": ["asc"],
            "item_set_id": [str(item_set["o:id"])],
        }
        assert "text/html" in raw.get(url + "/api").headers["content-type"]

    matches = client.list(
        "items",
        filters=property_filters(
            property_filter("dcterms:identifier", "eq", "duplicate-identifier")
        ),
        per_page=1,
        expected_ids=ids,
    )
    assert len(matches) == 3

    snapshot = capture_snapshot(client, item_set["o:id"])
    assert [item["o:id"] for item in snapshot.items] == ids
    assert len(snapshot.media) == 1
    media = snapshot.media[0]
    assert [m["o:id"] for m in client.list("media", filters=filters)] == [media["o:id"]]
    result = client.download(media["o:original_url"], tmp_path / "image.png")
    assert result.size == len(_PNG)
    assert result.sha256 == media["o:sha256"] == hashlib.sha256(_PNG).hexdigest()

    asset = client.create("assets", {}, files=Upload(content=_PNG, filename="asset.png"))
    assert asset["o:id"] > 0

    changed = client.patch(
        "items", ids[0], {"dcterms:title": literal("Changed", 1)}, replace_rdf_values=True
    )
    assert changed["dcterms:title"][0]["@value"] == "Changed"
    assert "dcterms:identifier" not in changed
    cleared = client.patch("items", ids[0], {"clear_property_values": [1]}, replace_rdf_values=True)
    assert "dcterms:title" not in cleared


async def test_stdio_server_reads_and_previews_and_sends_writes(instance: Instance) -> None:
    import sys

    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    url = instance.url
    transport = StdioTransport(
        sys.executable,
        ["-c", "from omeka_s_client.mcp import main; main()"],
        env={
            "OMEKA_URL": url,
            "OMEKA_KEY_IDENTITY": instance.identity,
            "OMEKA_KEY_CREDENTIAL": instance.credential,
            "OMEKA_MCP_ALLOW_WRITES": "true",
        },
    )
    async with Client(transport) as client:
        discovery = await client.call_tool("omeka_list_api_resources")
        assert any(record["o:id"] == "items" for record in discovery.data["records"])

        args = {
            "resource": "items",
            "payload": {"dcterms:identifier": literal("mcp-stdio-integration", 10)},
        }
        find = {
            "resource": "items",
            "property": "dcterms:identifier",
            "comparison": "eq",
            "value": "mcp-stdio-integration",
        }
        preview = await client.call_tool("omeka_create_record", args)
        assert preview.data["sent"] is False
        assert (await client.call_tool("omeka_find_records_by_property", find)).data[
            "records"
        ] == []

        result = await client.call_tool("omeka_create_record", {**args, "confirm": True})
        id = result.data["record"]["o:id"]
        assert result.data["sent"] is True
        fetched = await client.call_tool("omeka_get_record", {"resource": "items", "record_id": id})
        assert fetched.data["o:id"] == id
        assert (await client.call_tool("omeka_list_records_page", {"resource": "items"})).data[
            "total"
        ] >= 1
        listing = await client.call_tool(
            "omeka_list_all_records", {"resource": "items", "verify": True}
        )
        assert any(record["o:id"] == id for record in listing.data["records"])
        assert (
            len((await client.call_tool("omeka_find_records_by_property", find)).data["records"])
            == 1
        )
