"""Test the playground module that the browser worker runs."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omeka_s_client.transport import ConnectFailed, TransportRequest

_path = Path(__file__).parent.parent / "playground" / "playground.py"
_spec = importlib.util.spec_from_file_location("playground_module", _path)
assert _spec is not None and _spec.loader is not None
pg = importlib.util.module_from_spec(_spec)
sys.modules["playground_module"] = pg
_spec.loader.exec_module(pg)


def run(
    op: str, args: dict[str, Any] | None = None, demo: Any = None, **extra: Any
) -> dict[str, Any]:
    payload = {"op": op, "args": args or {}, **extra}
    send = extra.pop("send", None)
    payload.pop("send", None)
    return json.loads(pg.run_json(json.dumps(payload), demo or pg.Demo(), send))


class Sender:
    def __init__(
        self,
        total: bool = True,
        status: int = 200,
        body: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.seen: list[dict[str, str]] = []
        self.total, self.status, self.body, self.error = total, status, body, error

    def __call__(self, url: str, headers: dict[str, str]) -> Any:
        self.seen.append(headers)
        if self.error:
            raise self.error
        headers_out = {"Omeka-S-Total-Results": "2"} if self.total else {}
        body = [{"o:id": 1}, {"o:id": 2}] if self.body is None else self.body
        return SimpleNamespace(
            status_code=self.status, headers=headers_out, content=json.dumps(body).encode()
        )


def live(op: str, send: Any, args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"mode": "live", "url": "https://live.example.org", "op": op, "args": args or {}}
    return json.loads(pg.run_json(json.dumps(payload), pg.Demo(), send))


def test_seed_and_reset() -> None:
    demo = pg.Demo()
    assert run("delete", {"id": 1, "confirm": True}, demo)["ok"]
    assert len(demo.fake.records["items"]) == 11
    demo.reset()
    assert len(demo.fake.records["items"]) == 12


def test_get_page_list() -> None:
    out = run("get", {"id": 3})
    assert out["result"]["o:id"] == 3
    assert out["requests"] == ["GET https://demo.example.org/api/items/3"]
    assert "FakeOmeka(" in out["snippet"] and "client.get('items', 3)" in out["snippet"]
    out = run("page", {"per_page": 5, "filters": [["item_set_id", "2"]]})
    assert out["result"]["total"] == 6 and out["result"]["has_next"]
    out = run(
        "list",
        {
            "per_page": 4,
            "conditions": [
                {"property": "dcterms:identifier", "type": "eq", "value": "letter-001"},
                {
                    "property": "dcterms:identifier",
                    "type": "eq",
                    "value": "letter-002",
                    "joiner": "or",
                },
            ],
            "verify": True,
            "expected_ids": [1, 2],
        },
    )
    assert [r["o:id"] for r in out["result"]] == [1, 2]
    assert "joiner='or'" in out["snippet"] and "property_filters" in out["snippet"]


def test_writes() -> None:
    demo = pg.Demo()
    out = run("create", {"payload": {"o:title": "New"}}, demo)
    assert out["result"]["o:id"] == 13
    out = run(
        "patch", {"id": 13, "payload": {"o:title": "Changed"}, "replace_rdf_values": True}, demo
    )
    assert out["result"]["o:title"] == "Changed" and "replace_rdf_values=True" in out["snippet"]
    out = run("patch", {"id": 13, "payload": {"dcterms:title": []}}, demo)
    assert out["error"] == "RDFReplacementRequiredError"
    assert run("delete", {"id": 13, "confirm": True}, demo)["result"] == {"deleted": 13}
    out = run("get", {"id": 13}, demo)
    assert not out["ok"] and out["status"] == 404
    out = run("delete", {"id": 1}, demo)
    assert out["error"] == "ValidationError" and "confirm" in out["message"]


def test_upload() -> None:
    demo = pg.Demo()
    out = run("upload", {"payload": {"o:title": "Up"}, "filename": "a.txt", "text": "hi"}, demo)
    assert out["ok"] and "Upload(content=b'hi'" in out["snippet"]


def test_demo_filter_guard() -> None:
    pg.check_demo_filters(
        [
            ("sort_by", "id"),
            ("sort_order", "desc"),
            ("property[0][property]", "dcterms:title"),
            ("property[0][type]", "eq"),
            ("property[0][text]", "x"),
            ("property[0][joiner]", "or"),
        ]
    )
    bad = [
        [("fulltext_search", "x")],
        [("sort_by", "title")],
        [("sort_order", "up")],
        [("property[0][type]", "eq"), ("property[0][text]", "x")],
        [
            ("property[0][property]", "dcterms:title"),
            ("property[0][type]", "in"),
            ("property[0][text]", "x"),
        ],
        [("property[0][property]", "10"), ("property[0][type]", "eq"), ("property[0][text]", "x")],
        [("property[0][property]", "a:b"), ("property[0][type]", "eq")],
        [
            ("property[0][property]", "a:b"),
            ("property[0][type]", "eq"),
            ("property[0][text]", "x"),
            ("property[0][joiner]", "xor"),
        ],
    ]
    for pairs in bad:
        with pytest.raises(ValueError, match="FakeOmeka does not support filter"):
            pg.check_demo_filters(pairs)
    out = run("page", {"filters": [["fulltext_search", "x"]]})
    assert not out["ok"] and "does not support filter" in out["message"]
    assert out["snippet"] and out["requests"] == []


def test_bad_input() -> None:
    for payload in (
        "not json",
        '{"op": "nope"}',
        '{"op": "get"}',
        '{"op": "get", "args": {"id": 1, "x": 2}}',
    ):
        out = json.loads(pg.run_json(payload, pg.Demo()))
        assert out["error"] == "ValidationError" and out["snippet"] == ""
    out = run("get", {"id": 0})
    assert out["error"] == "ConfigurationError"
    out = run("get", {"id": 1, "resource": "bad/name"})
    assert not out["ok"]


def test_live_reads() -> None:
    send = Sender()
    out = live("list", send, {"per_page": 2})
    assert out["ok"] and out["warnings"] == []
    assert out["snippet"].endswith(
        "result = client.list('items', per_page=2, verify=False, expected_ids=None)"
    )
    assert "OmekaClient('https://live.example.org')" in out["snippet"]
    assert out["requests"][0].startswith("GET https://live.example.org/api/items")
    assert all(k.lower() in pg.SAFE_HEADERS for h in send.seen for k in h)
    out = live("get", Sender(total=False, body={"o:id": 1}), {"id": 1})
    assert out["ok"] and out["warnings"] == []
    out = live("page", Sender(total=False))
    assert out["ok"] and "total is unknown" in out["warnings"][0]
    out = live("list", Sender(total=False))
    assert out["error"] == "CorsExposureError" and "Access-Control-Expose-Headers" in out["message"]


def test_live_errors() -> None:
    out = live("get", Sender(error=OSError("blocked")), {"id": 1})
    assert not out["ok"] and out["error"] == "OmekaConnectionError"
    out = live("get", Sender(error=OSError()), {"id": 1})
    assert not out["ok"]
    assert live("get", Sender(status=404, body={}), {"id": 9})["status"] == 404
    for payload in (
        {"mode": "live", "url": "https://x.example", "op": "create", "args": {"payload": {}}},
        {"mode": "live", "op": "get", "args": {"id": 1}},
    ):
        out = json.loads(pg.run_json(json.dumps(payload), pg.Demo(), Sender()))
        assert out["error"] == "ValidationError"
    payload = {"mode": "live", "url": "https://x.example", "op": "get", "args": {"id": 1}}
    assert "sender" in json.loads(pg.run_json(json.dumps(payload), pg.Demo()))["message"]


def test_live_transport_refuses_writes() -> None:
    transport = pg.live_transport(Sender())
    with pytest.raises(ConnectFailed, match="only GET"):
        transport(TransportRequest("POST", "https://x.example/api/items"))
