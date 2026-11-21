"""Run OmekaClient calls for the browser playground. Pyodide and CPython 3.11+ both run this file.

The browser worker calls only Demo() and run_json().

>>> import json
>>> out = json.loads(run_json('{"op": "get", "args": {"resource": "items", "id": 1}}', Demo()))
>>> out["ok"], out["result"]["o:id"]
(True, 1)
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from omeka_s_client import (
    OmekaClient,
    OmekaError,
    Upload,
    property_filter,
    property_filters,
)
from omeka_s_client.testing import FakeOmeka
from omeka_s_client.transport import (
    ConnectFailed,
    TransportRequest,
    TransportResponse,
)

DEMO_URL = "https://demo.example.org"
LIVE_OPS = ("get", "page", "list")
SAFE_HEADERS = {"accept", "accept-language"}
_REQUIRED = {
    "get": ("id",),
    "patch": ("id", "payload"),
    "delete": ("id",),
    "create": ("payload",),
    "upload": ("payload", "filename", "text"),
}
_PLAIN_FILTERS = {"item_set_id", "item_id", "page", "per_page"}
_PROPERTY_KEY = re.compile(r"property\[([0-9]+)\]\[(property|type|text|joiner)\]")


class CorsExposureError(OmekaError):
    """Report that the browser hides a header the client needs.

    >>> str(CorsExposureError("hidden"))
    'hidden'
    """


class Condition(BaseModel):
    """One property search condition.

    >>> Condition(property="dcterms:title", type="eq", value="x").joiner is None
    True
    """

    property: str | int
    type: str
    value: str | int | None = None
    joiner: Literal["and", "or"] | None = None


class Args(BaseModel):
    """Arguments of an operation. Unknown names are errors.

    >>> Args().per_page
    10
    """

    model_config = ConfigDict(extra="forbid")

    resource: str = "items"
    id: int = 0
    page: int = 1
    per_page: int = 10
    filters: list[tuple[str, str]] = []
    conditions: list[Condition] = []
    verify: bool = False
    expected_ids: list[int] | None = None
    payload: dict[str, Any] = {}
    replace_rdf_values: bool = False
    confirm: bool = False
    filename: str = ""
    text: str = ""


class Payload(BaseModel):
    """Input of run_json. This is the I/O boundary.

    >>> Payload(op="get", args={"id": 1}).mode
    'demo'
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo", "live"] = "demo"
    url: str = ""
    op: Literal["get", "page", "list", "create", "patch", "delete", "upload"]
    args: Args = Args()

    @model_validator(mode="after")
    def _check(self) -> "Payload":
        if self.mode == "live":
            if self.op not in LIVE_OPS:
                raise ValueError("Live mode allows only get, page, and list.")
            if not self.url:
                raise ValueError("Live mode needs a url.")
        missing = [k for k in _REQUIRED.get(self.op, ()) if k not in self.args.model_fields_set]
        if missing:
            raise ValueError(f"{self.op} needs {', '.join(missing)}.")
        if self.op == "delete" and not self.args.confirm:
            raise ValueError("delete needs confirm set to true.")
        return self

    def pairs(self) -> list[tuple[str, str]]:
        """Return the query pairs of filters and conditions.

        >>> Payload(op="page", args={"filters": [["item_set_id", "1"]]}).pairs()
        [('item_set_id', '1')]
        """
        conditions = [
            property_filter(c.property, c.type, c.value, joiner=c.joiner)
            for c in self.args.conditions
        ]
        return [*self.args.filters, *property_filters(*conditions)]


def _values(text: str, number: int) -> list[dict[str, Any]]:
    return [{"type": "literal", "property_id": number, "@value": text}]


def seed() -> FakeOmeka:
    """Return a FakeOmeka with two item sets, twelve items, and media.

    >>> len(seed().records["items"])
    12
    """
    items = []
    for number in range(1, 13):
        sets = [{"o:id": 1}] if number <= 6 else []
        sets += [{"o:id": 2}] if 4 <= number <= 9 else []
        items.append(
            {
                "o:id": number,
                "o:title": f"Letter {number}",
                "o:item_set": sets,
                "dcterms:title": _values(f"Letter {number}", 1),
                "dcterms:identifier": _values(f"letter-{number:03d}", 10),
            }
        )
    media = [{"o:id": n, "o:item": {"o:id": n}, "o:source": f"scan-{n}.jpg"} for n in (1, 2, 3, 3)]
    sets = [{"o:id": n, "o:title": f"Collection {n}"} for n in (1, 2)]
    return FakeOmeka({"items": items, "media": media, "item_sets": sets})


class Demo:
    """Hold the demo installation.

    >>> demo = Demo()
    >>> demo.fake.records["items"].pop()["o:id"]
    12
    >>> demo.reset()
    >>> len(demo.fake.records["items"])
    12
    """

    def __init__(self) -> None:
        self.fake = seed()

    def reset(self) -> None:
        """Restore the seed data."""
        self.fake = seed()


def check_demo_filters(pairs: Sequence[tuple[str, str]]) -> None:
    """Reject a filter that FakeOmeka would ignore without a message.

    >>> check_demo_filters([("item_set_id", "1")])
    >>> check_demo_filters([("fulltext_search", "x")])
    Traceback (most recent call last):
    ValueError: FakeOmeka does not support filter fulltext_search.
    """
    rows: dict[str, dict[str, str]] = {}
    for key, value in pairs:
        if (
            key in _PLAIN_FILTERS
            or (key == "sort_by" and value == "id")
            or (key == "sort_order" and value in ("asc", "desc"))
        ):
            continue
        match = _PROPERTY_KEY.fullmatch(key)
        if match is None:
            raise ValueError(f"FakeOmeka does not support filter {key}.")
        rows.setdefault(match[1], {})[match[2]] = value
    for index, row in rows.items():
        term = row.get("property", "")
        if (
            row.get("type") != "eq"
            or not term
            or term.isdecimal()
            or "text" not in row
            or row.get("joiner", "and") not in ("and", "or")
        ):
            raise ValueError(
                f"FakeOmeka does not support filter property[{index}]. "
                "Use a term, type eq, and a text value."
            )


@dataclass
class LiveTransport:
    """Send GET requests through a browser sender with CORS-safe headers.

    >>> from types import SimpleNamespace as R
    >>> live = LiveTransport(lambda url, headers: R(status_code=200, headers={}, content=b"x"))
    >>> live(TransportRequest("GET", "https://a.example/api/items/1")).status
    200
    """

    send: Callable[..., Any]
    requests: list[str] = field(default_factory=list)
    totals: list[bool] = field(default_factory=list)

    def __call__(self, request: TransportRequest, /) -> TransportResponse:
        if request.method != "GET":
            raise ConnectFailed("Live mode allows only GET requests.")
        self.requests.append(f"GET {request.url}")
        headers = {k: v for k, v in request.headers.items() if k.lower() in SAFE_HEADERS}
        try:
            response = self.send(request.url, headers=headers)
        except OSError as error:
            raise ConnectFailed(str(error) or "The request failed. CORS may block it.") from None
        received = {str(k).lower() for k in response.headers}
        tail = urlsplit(request.url).path.rpartition("/api/")[2]
        if response.status_code == 200 and tail and "/" not in tail:
            self.totals.append("omeka-s-total-results" in received)
        return TransportResponse(response.status_code, dict(response.headers), response.content)

    @property
    def total_hidden(self) -> bool:
        """Report whether a list response lacked the total header.

        >>> LiveTransport(print).total_hidden
        False
        """
        return not all(self.totals)


def live_transport(send: Callable[..., Any]) -> LiveTransport:
    """Wrap a sender such as pyodide.http.pyxhr.get.

    >>> live_transport(print).requests
    []
    """
    return LiveTransport(send)


def _upload_payload(args: Args) -> dict[str, Any]:
    media = [{"o:ingester": "upload", "file_index": 0, "o:source": args.filename}]
    return {**args.payload, "o:media": media}


def _filters_code(payload: Payload) -> str:
    parts = [repr(pair) for pair in payload.args.filters]
    if payload.args.conditions:
        calls = []
        for c in payload.args.conditions:
            extra = f", joiner={c.joiner!r}" if c.joiner else ""
            calls.append(f"property_filter({c.property!r}, {c.type!r}, {c.value!r}{extra})")
        parts.append(f"*property_filters({', '.join(calls)})")
    return f", filters=[{', '.join(parts)}]" if parts else ""


def snippet(payload: Payload) -> str:
    """Build the equivalent Python code.

    >>> print(snippet(Payload(mode="live", url="https://a.example", op="get", args={"id": 2})))
    from omeka_s_client import OmekaClient
    <BLANKLINE>
    with OmekaClient('https://a.example') as client:
        result = client.get('items', 2)
    """
    a = payload.args
    res = repr(a.resource)
    flt = _filters_code(payload)
    calls = {
        "get": f"client.get({res}, {a.id})",
        "page": f"client.page({res}, page={a.page}, per_page={a.per_page}{flt})",
        "list": (
            f"client.list({res}, per_page={a.per_page}{flt}, verify={a.verify}"
            f", expected_ids={a.expected_ids})"
        ),
        "create": f"client.create({res}, {a.payload!r})",
        "patch": f"client.patch({res}, {a.id}, {a.payload!r}"
        + (", replace_rdf_values=True)" if a.replace_rdf_values else ")"),
        "delete": f"client.delete({res}, {a.id})",
        "upload": (
            f"client.create('items', {_upload_payload(a)!r}, "
            f"files=[Upload(content={a.text.encode()!r}, filename={a.filename!r})])"
        ),
    }
    call = calls[payload.op]
    names = ["OmekaClient"]
    if a.conditions:
        names += ["property_filter", "property_filters"]
    if payload.op == "upload":
        names.append("Upload")
    lines = [f"from omeka_s_client import {', '.join(sorted(names))}"]
    if payload.mode == "live":
        opener = f"with OmekaClient({payload.url!r}) as client:"
    else:
        lines.append("from omeka_s_client.testing import FakeOmeka")
        lines += ["", "fake = FakeOmeka(records)  # your own test data"]
        opener = f"with OmekaClient({DEMO_URL!r}, transport=fake) as client:"
    return "\n".join([*lines, "", opener, f"    result = {call}"])


def _execute(client: OmekaClient, payload: Payload) -> Any:
    a = payload.args
    pairs = payload.pairs()
    match payload.op:
        case "get":
            return client.get(a.resource, a.id)
        case "page":
            return asdict(client.page(a.resource, filters=pairs, page=a.page, per_page=a.per_page))
        case "list":
            return client.list(
                a.resource,
                filters=pairs,
                per_page=a.per_page,
                verify=a.verify,
                expected_ids=a.expected_ids,
            )
        case "create":
            return client.create(a.resource, a.payload)
        case "patch":
            return client.patch(
                a.resource, a.id, a.payload, replace_rdf_values=a.replace_rdf_values
            )
        case "delete":
            client.delete(a.resource, a.id)
            return {"deleted": a.id}
        case _:
            upload = Upload(content=a.text.encode(), filename=a.filename)
            return client.create("items", _upload_payload(a), files=[upload])


def _message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg'].removeprefix('Value error, ')}".lstrip(": ")
            for e in error.errors()
        )
    return str(error)


def run_json(payload_json: str, demo: Demo, send: Callable[..., Any] | None = None) -> str:
    """Run one operation. Take JSON and return JSON.

    >>> out = json.loads(run_json('{"op": "delete", "args": {"id": 1}}', Demo()))
    >>> out["ok"], out["error"]
    (False, 'ValidationError')
    """
    code = ""
    warnings: list[str] = []
    live: LiveTransport | None = None
    before = len(demo.fake.requests)
    try:
        payload = Payload.model_validate_json(payload_json)
        code = snippet(payload)
        if payload.mode == "live":
            if send is None:
                raise ValueError("Live mode needs a sender.")
            live = live_transport(send)
            client = OmekaClient(payload.url, transport=live, max_retries=0, sleep=_no_sleep)
        else:
            check_demo_filters(payload.pairs())
            client = OmekaClient(DEMO_URL, transport=demo.fake, max_retries=0, sleep=_no_sleep)
        with client:
            result = _execute(client, payload)
        if live is not None and live.total_hidden:
            if payload.op == "list":
                raise CorsExposureError(
                    "The browser hides Omeka-S-Total-Results, so the listing may be incomplete. "
                    "The server must send Access-Control-Expose-Headers: "
                    "Link, Omeka-S-Total-Results.",
                    operation="GET",
                )
            warnings.append("The total is unknown. The server hides Omeka-S-Total-Results.")
        out: dict[str, Any] = {"ok": True, "result": result}
    except (OmekaError, ValueError) as error:
        status = getattr(error, "status", None)
        out = {
            "ok": False,
            "error": type(error).__name__,
            "message": _message(error),
            "status": status,
        }
    out |= {"snippet": code, "warnings": warnings}
    out["requests"] = (
        live.requests
        if live is not None
        else [f"{r.method} {r.url}" for r in demo.fake.requests[before:]]
    )
    return json.dumps(out, default=str)


def _no_sleep(_: float) -> None:
    """Never block the browser.

    >>> _no_sleep(1.0)
    """
