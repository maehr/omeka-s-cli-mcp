from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from omeka_s_client import (
    ConfigurationError,
    OmekaClient,
    Snapshot,
    SnapshotConsistencyError,
    SnapshotError,
    TransportRequest,
    TransportResponse,
    capture_snapshot,
    read_snapshot,
    write_snapshot,
)
from omeka_s_client.snapshots import Variant
from omeka_s_client.testing import FakeOmeka

FIXTURES = Path(__file__).with_name("fixtures") / "legacy"


@pytest.mark.parametrize(
    "fixture",
    [
        "validator-raw",
        "validator-transformed",
        "validator-plain-2025",
        "omeka2dsp-mixed",
        "single-object",
    ],
)
def test_read_legacy_and_preserve_jsonld(fixture: str) -> None:
    expected = read_snapshot(FIXTURES / "validator-raw")
    loaded = read_snapshot(FIXTURES / fixture)
    assert loaded.source == "https://catalog.example.org/collection"
    assert loaded.items == expected.items
    assert loaded.media == expected.media
    assert loaded.item_set_id == (8 if fixture.startswith("validator") else None)
    assert loaded.items[0]["x-custom"]["preserve"] == [None, False, 5.5]


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("missing", "Missing media"),
        ("items", "Invalid items"),
        ("count", "items_count differs"),
        ("source", "different sources"),
    ],
)
def test_invalid_legacy_snapshot(fixture: str, message: str) -> None:
    with pytest.raises(SnapshotError, match=message):
        read_snapshot(FIXTURES / f"invalid-{fixture}")


@pytest.mark.parametrize(
    ("file", "content", "error"),
    [
        ("items_transformed.json", b"{bad", "Cannot read"),
        ("item_set.json", b"null", "Invalid item set"),
        ("media.json", b"[null]", "Invalid media"),
        ("snapshot.json", b"[]", "Invalid snapshot manifest"),
        ("snapshot.json", b'{"items_count":"1"}', "Invalid snapshot manifest"),
        ("snapshot.json", b'{"source":false}', "Invalid snapshot manifest"),
        ("snapshot.json", b'{"media_count":null}', "media_count differs"),
    ],
)
def test_snapshot_invalid_preferred_file(
    file: str,
    content: bytes,
    error: str,
    tmp_path: Path,
) -> None:
    write_snapshot(tmp_path / "snapshot", Snapshot("", None, [], []))
    root = tmp_path / "snapshot"
    (root / file).write_bytes(content)
    with pytest.raises(SnapshotError, match=error):
        read_snapshot(root)


@pytest.mark.parametrize(
    ("variant", "manifest", "suffix"),
    [
        ("", "snapshot.json", ""),
        ("raw", "download_metadata.json", "_raw"),
        ("transformed", "transformation_metadata.json", "_transformed"),
    ],
)
def test_snapshot_write_roundtrip(
    variant: Variant,
    manifest: str,
    suffix: str,
    tmp_path: Path,
) -> None:
    source = read_snapshot(FIXTURES / "validator-raw")
    target = tmp_path / "new"
    assert write_snapshot(target, source, variant=variant, extra={"custom": "Grüezi"}) == target
    logical = ("item_set", "items", "media")
    expected_files = {name: f"{name}{suffix}.json" for name in logical}
    assert {file.name for file in target.iterdir()} == {*expected_files.values(), manifest}
    metadata = json.loads((target / manifest).read_text("utf-8"))
    assert metadata["format"] == "omeka-s-snapshot" and metadata["format_version"] == 1
    assert metadata["item_set_id"] == 8 and metadata["items_count"] == metadata["media_count"] == 1
    assert metadata["status"] == variant and metadata["custom"] == "Grüezi"
    assert metadata["created_at"].endswith("+00:00")
    assert metadata["files"] == {key: f"new/{name}" for key, name in expected_files.items()}
    assert read_snapshot(target) == source
    for file in target.iterdir():
        assert file.read_bytes().endswith(b"\n")
        if os.name != "nt":
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_source_fallback_and_manifest_source_agreement(tmp_path: Path) -> None:
    (tmp_path / "items.json").write_text('[{"@id": 8}, {"@id": "/other"}]')
    (tmp_path / "media.json").write_text('{"@id":"https://example.org/another/api/media/7"}')
    assert read_snapshot(tmp_path).source == "https://example.org/another"
    (tmp_path / "media.json").write_text("[]")
    assert read_snapshot(tmp_path).source == ""
    for manifest in ("download_metadata.json", "snapshot.json"):
        (tmp_path / manifest).write_text('{"source":"https://example.org","custom":1}')
    assert read_snapshot(tmp_path).source == "https://example.org"


def test_snapshot_write_validates_inputs(tmp_path: Path) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(SnapshotError, match="already exists"):
        write_snapshot(destination, Snapshot("", None, [], []))
    destination = tmp_path / "new"
    with pytest.raises(SnapshotError, match="Extra metadata"):
        write_snapshot(destination, Snapshot("", None, [], []), extra={"source": "overwrite"})
    source: Any = False
    item_set: Any = []
    for snapshot in (Snapshot(source, None, [], []), Snapshot("", item_set, [], [])):
        with pytest.raises(SnapshotError):
            write_snapshot(destination, snapshot)
    with pytest.raises(SnapshotError, match="variant"):
        variant: Any = "unknown"
        write_snapshot(destination, Snapshot("", None, [], []), variant=variant)
    assert list(tmp_path.iterdir()) == [tmp_path / "existing"]


def test_snapshot_write_failure_cleans_temporary_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "new"

    def fail(_: int) -> None:
        raise OSError(errno.EIO, "Test disk error")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(SnapshotError, match="Cannot write"):
        write_snapshot(target, Snapshot("", {"o:id": 1}, [], []))
    assert list(tmp_path.iterdir()) == []


def test_snapshot_write_detects_destination_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import omeka_s_client.snapshots as snapshots

    target = tmp_path / "new"

    def create_destination(_: Path) -> None:
        target.mkdir()

    monkeypatch.setattr(snapshots, "_sync_directory", create_destination)
    with pytest.raises(SnapshotError, match="already exists"):
        write_snapshot(target, Snapshot("", None, [], []))
    assert list(tmp_path.iterdir()) == [target]
    assert list(target.iterdir()) == []


def test_capture_orders_media_by_parent_reference() -> None:
    def media(id: int, parent: int) -> dict[str, Any]:
        return {"o:id": id, "o:item": {"o:id": parent}}

    data = {
        "item_sets": [{"o:id": 7}],
        "items": [
            {"o:id": 5, "o:item_set": [{"o:id": 7}], "o:media": [{"o:id": 9}, {"o:id": 2}]},
            {"o:id": 1, "o:item_set": [{"o:id": 7}]},
            {"o:id": 2, "o:item_set": [{"o:id": 7}], "o:media": []},
        ],
        "media": [media(2, 5), media(9, 5), media(3, 1)],
    }
    fake = FakeOmeka(data)
    with OmekaClient("https://example.org/collection", transport=fake) as client:
        snapshot = capture_snapshot(client, 7, workers=2)
        with pytest.raises(ConfigurationError):
            capture_snapshot(client, 7, workers=False)
    assert snapshot.source == "https://example.org/collection"
    assert snapshot.item_set_id == 7
    assert [item["o:id"] for item in snapshot.items] == [1, 2, 5]
    assert [record["o:id"] for record in snapshot.media] == [3, 9, 2]
    orders = [
        parse_qs(urlsplit(req.url).query)["sort_order"]
        for req in fake.requests
        if urlsplit(req.url).path.endswith("/api/items")
    ]
    assert orders == [["asc"], ["desc"]]


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("changed", "Missing examples"),
        ("parent", "expected parent"),
        ("missing", "Missing examples"),
        ("invalid", "invalid media"),
        ("duplicate", "duplicate media references"),
        ("same-id", "multiple items"),
    ],
)
def test_capture_inconsistency(scenario: str, message: str) -> None:
    def transport(request: TransportRequest) -> TransportResponse:
        url = urlsplit(request.url)
        query = parse_qs(url.query)
        if url.path.endswith("item_sets/1"):
            return TransportResponse(200, content=b'{"o:id":1}')
        if url.path.endswith("/items"):
            item_id = 5 if scenario == "changed" and query["sort_order"] == ["desc"] else 6
            refs: Any = [{"o:id": 2}]
            if scenario == "invalid":
                refs = [{}]
            if scenario == "duplicate":
                refs += refs
            records = [{"o:id": item_id, "o:media": refs}]
            if scenario == "same-id":
                records.append({"o:id": 7, "o:media": refs})
        else:
            parent = 4 if scenario == "parent" else int(query["item_id"][0])
            records = [] if scenario == "missing" else [{"o:id": 2, "o:item": {"o:id": parent}}]
        return TransportResponse(
            200, {"Omeka-S-Total-Results": str(len(records))}, json.dumps(records).encode()
        )

    with (
        OmekaClient("https://example.org", transport=transport) as client,
        pytest.raises(SnapshotConsistencyError, match=message),
    ):
        capture_snapshot(client, 1)


@pytest.mark.parametrize("can_sync", [True, False])
def test_directory_fsync_is_platform_specific(
    can_sync: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omeka_s_client.snapshots as snapshots

    ops = []

    def opened(path: Path, flags: int) -> int:
        ops.append((path, flags))
        return 7

    monkeypatch.setattr(snapshots, "_CAN_SYNC_DIRECTORY", can_sync)
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "fsync", lambda fd: ops.append(("fsync", fd)))
        patch.setattr(os, "close", lambda fd: ops.append(("close", fd)))
        snapshots._sync_directory(tmp_path)
    assert ops == ([(tmp_path, os.O_RDONLY), ("fsync", 7), ("close", 7)] if can_sync else [])
