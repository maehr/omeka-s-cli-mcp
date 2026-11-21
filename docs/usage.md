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

Records are JSON-LD dictionaries. The client preserves unknown keys and values. Use query pairs to preserve repeated keys and bracketed keys. Use `expected_ids` to check an exact set of IDs. This option enables listing verification.

| Method | Result |
| --- | --- |
| `get(resource, id)` | One record |
| `page(resource, filters=..., page=..., per_page=...)` | Records, page number, page size, an optional total, and the next-page flag |
| `list(resource, filters=..., verify=..., expected_ids=...)` | All matching records in page order |
| `download(url, destination)` | Destination path, byte count, and SHA-256 digest |

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

Pass `replace_rdf_values=True` when the payload contains RDF values or `clear_property_values`. The client sends each write once. Check the record before you repeat a write after an unknown outcome or a server error. [Security](security.md)

### Delete a record

**Caution.** Verify the installation, resource, and ID before you call `delete`. Omeka S permanently deletes the record.

Use `client.delete("items", 123)` with an authenticated client that has permission to delete the record. The call sends the request immediately and returns `None` on success. A missing record raises `OmekaHTTPError` with status `404`.

Some Omeka S versions can return HTTP 500 after they delete an item. [Compatibility](compatibility.md)

## Capture a snapshot

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
