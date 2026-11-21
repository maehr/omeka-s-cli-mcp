"""In-memory transport for tests that use the Omeka client."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from threading import Lock
from urllib.parse import parse_qs, urlencode, urlsplit

from pydantic import TypeAdapter, ValidationError

from .transport import TransportRequest, TransportResponse
from .types import Record

_PROPERTY_FIELD = re.compile(r"property\[([0-9]+)\]\[(property|type|text|joiner)\]")
_RECORD = TypeAdapter(Record)


class FakeOmeka:
    """Process common Omeka API requests in memory and record each request.

    >>> from omeka_s_client import OmekaClient
    >>> fake = FakeOmeka({"items": [{"o:id": 1, "o:title": "Example"}]})
    >>> with OmekaClient("https://example.org", transport=fake) as client:
    ...     print(client.get("items", 1)["o:title"])
    Example
    """

    def __init__(
        self,
        records: Mapping[str, Sequence[Record]] | None = None,
        *,
        files: Mapping[str, bytes] | None = None,
    ) -> None:
        self.requests: list[TransportRequest] = []
        self.records = {key: deepcopy(list(values)) for key, values in (records or {}).items()}
        self.files = dict(files or {})
        self._lock = Lock()

    def __call__(self, request: TransportRequest) -> TransportResponse:
        with self._lock:
            self.requests.append(request)
            return self._respond(request)

    def _respond(self, request: TransportRequest) -> TransportResponse:
        parsed = urlsplit(request.url)
        if request.method == "GET" and parsed.path in self.files:
            return TransportResponse(200, content=self.files[parsed.path])
        if "/api/" not in parsed.path:
            return _response(404, {})
        resource, _, id = parsed.path.rsplit("/api/", 1)[-1].partition("/")
        if resource == "api_resources" and request.method == "GET":
            return _response(200, [{"o:id": name} for name in sorted(self.records)])
        if request.method == "POST":
            content_type = request.headers.get("content-type", "")
            payload = (
                _multipart_payload(request.content, content_type)
                if content_type.partition(";")[0].strip().lower() == "multipart/form-data"
                else _json_payload(request)
            )
            if payload is None:
                return _response(400, {})
            records = self.records.setdefault(resource, [])
            next_id = max((record["o:id"] for record in records), default=0) + 1
            created = {**payload, "o:id": next_id}
            records.append(created)
            return _response(201, created)
        if resource not in self.records:
            return _response(404, {})
        records = self.records[resource]
        if id:
            for index, record in enumerate(records):
                if str(record["o:id"]) == id:
                    if request.method == "GET":
                        return _response(200, record)
                    if request.method == "PATCH":
                        patch = _json_payload(request)
                        if patch is None:
                            return _response(400, {})
                        record.update(patch)
                        return _response(200, record)
                    if request.method == "DELETE":
                        del records[index]
                        return TransportResponse(204)
            return _response(404, {})
        if request.method != "GET":
            return _response(405, {})
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "item_set_id" in query:
            records = [
                record
                for record in records
                if any(
                    str(ref["o:id"]) in query["item_set_id"] for ref in record.get("o:item_set", [])
                )
            ]
        if "item_id" in query:
            records = [
                record
                for record in records
                if str(record.get("o:item", {}).get("o:id")) in query["item_id"]
            ]
        property_groups = _exact_property_groups(query)
        if property_groups:
            records = [
                record
                for record in records
                if any(
                    all(_matches_property(record, term, text) for term, text in group)
                    for group in property_groups
                )
            ]
        records = sorted(
            records, key=lambda record: record["o:id"], reverse=query.get("sort_order") == ["desc"]
        )
        page = int(query.get("page", ["1"])[0])
        size = int(query.get("per_page", ["50"])[0])
        headers = {"Omeka-S-Total-Results": str(len(records))}
        if page * size < len(records):
            query["page"] = [str(page + 1)]
            headers["Link"] = f'<?{urlencode(query, doseq=True)}>; rel="next"'
        return _response(200, records[(page - 1) * size : page * size], headers)


def _json_payload(request: TransportRequest) -> Record | None:
    if request.headers.get("content-type") == "application/json":
        value = json.loads(request.content)
        if isinstance(value, dict):
            return value
    return None


def _multipart_payload(content: bytes, content_type: str) -> Record | None:
    header = f"Content-Type: {content_type}\r\n\r\n".encode()
    message = BytesParser(policy=policy.default).parsebytes(header + content)
    if message.defects:
        return None
    fields = [
        part.get_payload(decode=True)
        for part in message.iter_parts()
        if part.get_content_disposition() == "form-data"
        and part.get_param("name", header="content-disposition") == "data"
        and part.get_filename() is None
    ]
    if len(fields) != 1 or not isinstance(fields[0], bytes):
        return None
    try:
        return _RECORD.validate_json(fields[0])
    except ValidationError:
        return None


def _exact_property_groups(query: dict[str, list[str]]) -> list[list[tuple[str, str]]]:
    rows: dict[str, dict[str, str]] = {}
    for key, values in query.items():
        if match := _PROPERTY_FIELD.fullmatch(key):
            index, field = match.groups()
            rows.setdefault(index, {})[field] = values[-1]

    # Each OR starts a new group so that AND binds more tightly.
    groups: list[list[tuple[str, str]]] = []
    for row in rows.values():
        term = row.get("property", "")
        if row.get("type") != "eq" or not term or term.isdecimal() or "text" not in row:
            continue
        if not groups or row.get("joiner") == "or":
            groups.append([])
        groups[-1].append((term, row["text"]))
    return groups


def _matches_property(record: Record, term: str, text: str) -> bool:
    values = record.get(term)
    return isinstance(values, list) and any(
        isinstance(value, Mapping)
        and (
            value.get("@value") == text or (value.get("type") == "uri" and value.get("@id") == text)
        )
        for value in values
    )


def _response(
    status: int, value: Record | list[Record], headers: dict[str, str] | None = None
) -> TransportResponse:
    return TransportResponse(status, headers or {}, json.dumps(value).encode())
