"""In-memory transport for tests that use the Omeka client."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from threading import Lock
from urllib.parse import parse_qs, urlencode, urlsplit

from .transport import TransportRequest, TransportResponse
from .types import Record


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
            records = self.records.setdefault(resource, [])
            payload = _json_payload(request)
            if payload is None:
                return _response(400, {})
            next_id = max((record["o:id"] for record in records), default=0) + 1
            created = {**payload, "o:id": next_id}
            records.append(created)
            return _response(201, created)
        if resource not in self.records:
            return _response(404, {})
        records = self.records[resource]
        if id:
            for record in records:
                if str(record["o:id"]) == id:
                    if request.method == "GET":
                        return _response(200, record)
                    if request.method == "PATCH":
                        patch = _json_payload(request)
                        if patch is None:
                            return _response(400, {})
                        record.update(patch)
                        return _response(200, record)
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


def _response(
    status: int, value: Record | list[Record], headers: dict[str, str] | None = None
) -> TransportResponse:
    return TransportResponse(status, headers or {}, json.dumps(value).encode())
