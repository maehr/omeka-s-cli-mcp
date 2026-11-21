"""Capture, read, and write metadata snapshots."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ._listing import positive_integer
from ._manifest import Manifest
from .client import OmekaClient
from .errors import (
    ConfigurationError,
    IncompleteListingError,
    SnapshotConsistencyError,
    SnapshotError,
)
from .types import Record

Variant = Literal["", "raw", "transformed"]
_MANIFESTS = {
    "": "snapshot.json",
    "transformed": "transformation_metadata.json",
    "raw": "download_metadata.json",
}
_SUFFIXES = ("_transformed", "", "_raw")
_CAN_SYNC_DIRECTORY = os.name != "nt"


@dataclass(slots=True)
class Snapshot:
    """Hold the source and JSON-LD records of a metadata snapshot.

    >>> Snapshot("https://example.org", {"o:id": 1}, [], []).item_set_id
    1
    """

    source: str
    item_set: Record | None
    items: list[Record]
    media: list[Record]

    @property
    def item_set_id(self) -> int | None:
        """Give the item set ID when the snapshot includes one."""
        value = self.item_set.get("o:id") if self.item_set else None
        return value if positive_integer(value) else None


def _read_media(client: OmekaClient, item: Record) -> list[Record]:
    item_id = item["o:id"]
    refs = item.get("o:media")
    ids = None
    if refs is not None:
        if not isinstance(refs, list) or any(
            not isinstance(ref, dict) or not positive_integer(ref.get("o:id")) for ref in refs
        ):
            raise SnapshotConsistencyError(f"Item {item_id} has an invalid media reference.")
        ids = [ref["o:id"] for ref in refs]
        if len(ids) != len(set(ids)):
            raise SnapshotConsistencyError(f"Item {item_id} has duplicate media references.")
    media = client.list("media", filters={"item_id": item_id}, verify=True, expected_ids=ids)
    for record in media:
        parent = record.get("o:item")
        parent_id = parent.get("o:id") if isinstance(parent, dict) else None
        if not positive_integer(parent_id) or parent_id != item_id:
            raise SnapshotConsistencyError(
                f"Media {record['o:id']} does not have the expected parent item {item_id}."
            )
    by_id = {record["o:id"]: record for record in media}
    return [by_id[id] for id in (sorted(by_id) if ids is None else ids)]


def capture_snapshot(client: OmekaClient, item_set_id: int, *, workers: int = 4) -> Snapshot:
    """Capture the members of an item set and their media.

    These checks detect some concurrent changes.
    They cannot establish a single point in time across requests.

    >>> from omeka_s_client.testing import FakeOmeka
    >>> fake = FakeOmeka({"item_sets": [{"o:id": 7}], "items": []})
    >>> with OmekaClient("https://example.org", transport=fake) as client:
    ...     print(capture_snapshot(client, 7).items)
    []
    """
    if not positive_integer(workers):
        raise ConfigurationError("Workers must be a positive integer.")
    item_set = client.get("item_sets", item_set_id)
    filters = {"item_set_id": item_set_id}
    try:
        items = client.list("items", filters=filters, verify=True)
        client._list(
            "items", filters=filters, expected_ids=[item["o:id"] for item in items], order="desc"
        )
        items.sort(key=lambda item: item["o:id"])
        with ThreadPoolExecutor(max_workers=workers) as pool:
            media = [
                record
                for batch in pool.map(lambda item: _read_media(client, item), items)
                for record in batch
            ]
    except IncompleteListingError as error:
        raise SnapshotConsistencyError(
            str(error), operation=error.operation, resource=error.resource
        ) from None
    if len({record["o:id"] for record in media}) != len(media):
        raise SnapshotConsistencyError("A media ID appears under multiple items.")
    return Snapshot(client.installation_url, item_set, items, media)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        raise SnapshotError(f"Cannot read {path.name}.") from None


def _group_file(directory: Path, name: str) -> Path | None:
    for suffix in _SUFFIXES:
        candidate = directory / f"{name}{suffix}.json"
        if os.path.lexists(candidate):
            return candidate
    return None


def _records(value: object, name: str, *, legacy: bool = False) -> list[Record]:
    if legacy and isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or any(not isinstance(record, dict) for record in value):
        raise SnapshotError(f"Invalid {name} records in snapshot.")
    return value


def _source(item_set: Record | None, items: list[Record], media: list[Record]) -> str:
    for group in ((item_set,) if item_set is not None else (), items, media):
        for record in group:
            identifier = record.get("@id")
            if isinstance(identifier, str) and "/api/" in identifier:
                return identifier.rsplit("/api/", 1)[0]
    return ""


def read_snapshot(directory: str | os.PathLike[str]) -> Snapshot:
    """Read metadata files and check each manifest that exists.

    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     path = write_snapshot(Path(directory) / "sample", Snapshot("", None, [], []))
    ...     print(read_snapshot(path).media)
    []
    """
    root = Path(directory)
    item_set_file = _group_file(root, "item_set")
    item_set = _read_json(item_set_file) if item_set_file is not None else None
    if item_set_file is not None and not isinstance(item_set, dict):
        raise SnapshotError("Invalid item set record in snapshot.")

    groups = []
    for name in ("items", "media"):
        file = _group_file(root, name)
        if file is None:
            raise SnapshotError(f"Missing {name} file in snapshot.")
        groups.append(_records(_read_json(file), name, legacy=True))
    items, media = groups
    source = None
    for name in _MANIFESTS.values():
        path = root / name
        if not os.path.lexists(path):
            continue
        try:
            manifest = Manifest.model_validate(_read_json(path))
        except ValidationError:
            raise SnapshotError(f"Invalid snapshot manifest {name}.") from None
        for count_field, records in (("items_count", items), ("media_count", media)):
            if count_field in manifest.model_fields_set and getattr(manifest, count_field) != len(
                records
            ):
                raise SnapshotError(f"Snapshot count {count_field} differs in {name}.")
        if manifest.source is not None:
            if source is not None and source != manifest.source:
                raise SnapshotError("Snapshot manifests have different sources.")
            source = manifest.source
    if source is None:
        source = _source(item_set, items, media)
    return Snapshot(source, item_set, items, media)


def _write_json(path: Path, value: Any) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    if _CAN_SYNC_DIRECTORY:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_snapshot(
    directory: str | os.PathLike[str],
    snapshot: Snapshot,
    *,
    variant: Variant = "",
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write a complete snapshot to a new directory.

    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     path = write_snapshot(Path(directory) / "sample", Snapshot("", None, [], []))
    ...     print((path / "snapshot.json").is_file())
    True
    """
    path = Path(directory)
    if variant not in _MANIFESTS:
        raise SnapshotError("Invalid snapshot variant.")
    if os.path.lexists(path):
        raise SnapshotError("Snapshot destination already exists.")
    if snapshot.item_set is not None and not isinstance(snapshot.item_set, dict):
        raise SnapshotError("Invalid item set record in snapshot.")
    items = _records(snapshot.items, "items")
    media = _records(snapshot.media, "media")
    if not isinstance(snapshot.source, str):
        raise SnapshotError("Invalid snapshot source.")
    now = datetime.now(UTC)
    suffix = f"_{variant}" if variant else ""
    contents = {"items": items, "media": media}
    if snapshot.item_set is not None:
        contents = {"item_set": snapshot.item_set, **contents}
    filenames = {name: f"{name}{suffix}.json" for name in contents}
    metadata = {
        "format": "omeka-s-snapshot",
        "format_version": 1,
        "source": snapshot.source,
        "item_set_id": snapshot.item_set_id,
        "items_count": len(items),
        "media_count": len(media),
        "created_at": now.isoformat(),
        "files": {name: (Path(path.name) / file).as_posix() for name, file in filenames.items()},
        "status": variant,
        "timestamp": now.strftime("%Y%m%d_%H%M%S"),
    }
    if extra and metadata.keys() & extra.keys():
        raise SnapshotError("Extra metadata cannot replace snapshot manifest fields.")
    temp = None
    try:
        temp = Path(tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}."))
        for name, value in contents.items():
            _write_json(temp / filenames[name], value)
        _write_json(temp / _MANIFESTS[variant], {**metadata, **(extra or {})})
        _sync_directory(temp)
        if os.path.lexists(path):
            raise SnapshotError("Snapshot destination already exists.")
        temp.rename(path)
        temp = None
        return path
    except (OSError, ValueError, TypeError, RecursionError):
        raise SnapshotError("Cannot write snapshot.") from None
    finally:
        if temp is not None:
            shutil.rmtree(temp)
