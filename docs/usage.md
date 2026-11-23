# Python API

Import `OmekaClient` from `omeka_s_client`. Pass an installation URL with or without `/api/`. Use a context manager to close the client after the last request.

```python
import os

from omeka_s_client import OmekaClient, property_filter, property_filters

conditions = property_filters(property_filter("dcterms:identifier", "eq", "abc"))

with OmekaClient(
    "https://example.org/collection",
    key_identity=os.environ["OMEKA_KEY_IDENTITY"],
    key_credential=os.environ["OMEKA_KEY_CREDENTIAL"],
    timeout=30.0,
) as client:
    page = client.page("items", filters=conditions, per_page=20)
    matches = client.list("items", filters=conditions, verify=True)
```

The client covers five common REST operation patterns. It has no `PUT` method. [API coverage](api-coverage.md)

Records are JSON-LD dictionaries. The client preserves unknown keys and values. Use query pairs to preserve repeated keys and bracketed keys. Use `expected_ids` to check an exact set of IDs. This option enables listing verification.

| Method | Result |
| --- | --- |
| `get(resource, id)` | One record |
| `page(resource, filters=..., page=..., per_page=...)` | Records, page number, page size, an optional total, and the next-page flag |
| `list(resource, filters=..., verify=..., expected_ids=...)` | All matching records in page order |
| `download(url, destination)` | Destination path, byte count, and SHA-256 digest |

## Read lists

`page` reads one page. `list` reads all pages in the server order. `list(verify=True)` also checks that the listing is consistent.

```python
from omeka_s_client import OmekaClient
from omeka_s_client.testing import FakeOmeka

fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}, {"o:id": 3}]})
with OmekaClient("https://example.org", transport=fake) as client:
    first = client.page("items", per_page=2)  # 2 records, has_next is True
    every = client.list("items", per_page=2)  # 3 records, no checks
    checked = client.list("items", per_page=2, verify=True)  # 3 records, checked
```

A verified listing checks these conditions:

- Each record has a positive integer `o:id`.
- No ID appears twice.
- The total count stays the same on each page.
- The number of IDs agrees with the total count or with `expected_ids`.

A verified listing sorts by ID. Do not put `sort_by` or `sort_order` in the filters. The client raises `ConfigurationError` for these keys. The server must send a total count, or you must supply `expected_ids`.

**Note.** Verification checks only the records that the caller can see. It does not prove that the listing holds all records on the server. It does not give a consistent view at one point in time.

The client retries transient reads. A verified listing repeats the complete read after a consistency check fails. The client waits 2 s before the second attempt and 4 s before the third. Catch `IncompleteListingError` if each verification attempt fails. Set `max_records` on `list` to reject a listing above a record limit.

## Bypass caches

Set `cache_busting=True` when a proxy or cache returns stale lists. The client then adds a random `omeka_s_client_nonce` query parameter to each API GET request. It also sends `Pragma: no-cache`. The client never changes file downloads or writes. Do not use `omeka_s_client_nonce` as a filter name.

## Write records

**Caution.** Include every RDF value to retain when you send an RDF update. Omeka S can remove values that the payload omits.

Use `create(resource, payload)` for JSON. Pass `files=Upload(path=path)` for an asset. Pass a list of uploads for item media. Set `file_index` on each upload reference, starting at zero.

```python
from pathlib import Path

from omeka_s_client import OmekaClient, Upload

with OmekaClient(
    "https://example.org", key_identity="EXAMPLE_ID", key_credential="EXAMPLE_KEY"
) as client:
    item = client.create(
        "items",
        {"o:media": [{"o:ingester": "upload", "file_index": 0}]},
        files=[Upload(path=Path("image.png"))],
    )
    client.patch("items", item["o:id"], {"o:is_public": False})
```

Pass `replace_rdf_values=True` to `patch` when the payload contains RDF values or `clear_property_values`. Otherwise `patch` raises `RDFReplacementRequiredError`. The client sends each write once. Check the record before you repeat a write after an unknown outcome or a server error. [Security](security.md)

Read `client.has_api_keys` to check whether the client has both keys. It reports configured keys. It does not prove that the server accepts them.

### Update RDF values

A `patch` with RDF values replaces all RDF values of the record. To keep the other values, read the record first. Send all its RDF values with your change.

```python
from omeka_s_client import OmekaClient
from omeka_s_client.testing import FakeOmeka


def literal(value: str, property_id: int) -> dict[str, object]:
    return {"type": "literal", "property_id": property_id, "@value": value}


fake = FakeOmeka({"items": []})
with OmekaClient("https://example.org", transport=fake) as client:
    item = client.create(
        "items",
        {
            "dcterms:title": [literal("Old title", 1)],
            "dcterms:identifier": [literal("abc", 10)],
        },
    )
    current = client.get("items", item["o:id"])
    values = {
        key: value
        for key, value in current.items()
        if ":" in key and not key.startswith(("@", "o:", "o-")) and isinstance(value, list)
    }
    values["dcterms:title"] = [literal("New title", 1)]
    client.patch("items", item["o:id"], values, replace_rdf_values=True)
```

Use the property IDs of your installation. Read them from the `properties` resource.

### Delete a record

**Caution.** Verify the installation, resource, and ID before you call `delete`. Omeka S permanently deletes the record.

Use `client.delete("items", 123)` with an authenticated client that has permission to delete the record. The call sends the request immediately and returns `None` on success. A missing record raises `OmekaHTTPError` with status `404`.

Some Omeka S versions can return HTTP 500 after they delete an item. [Compatibility](compatibility.md)

## Capture a snapshot

**Caution.** A snapshot holds only the records that the client can read. An anonymous client reads only public records. Use API keys to include private records. Even with keys, the snapshot holds only the records that the user can see.

A snapshot holds JSON-LD metadata. It does not hold the original media files. Use `download` to save a file.

```python
from omeka_s_client import OmekaClient, capture_snapshot, read_snapshot, write_snapshot

with OmekaClient("https://example.org") as client:
    snapshot = capture_snapshot(client, 7)
write_snapshot("item-set-7", snapshot)
snapshot = read_snapshot("item-set-7")
```

The capture checks item membership and media relationships across requests. Concurrent edits can still occur between the requests. [Snapshot format](snapshot-format.md)

## Test offline

Pass a callable as `transport`. Receive a `TransportRequest` and return a `TransportResponse`. Use `omeka_s_client.testing.FakeOmeka` for basic in-memory record operations and pagination.

Pass uploads to `create` to test multipart requests. The fake stores the JSON record from the multipart request and skips file storage.

Use `eq` with a property term to search JSON-LD values. The fake uses case-sensitive comparisons for literal text and URIs. Combine clauses with `and` or `or`. The fake ignores numeric property IDs and other comparison types.

[Omeka S REST API reference](https://omeka.org/s/docs/developer/api/rest_api/)
