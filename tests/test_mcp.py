from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import typer
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import TextResourceContents
from typer.testing import CliRunner

from omeka_s_client import TransportRequest, TransportResponse
from omeka_s_client.cli import build_app
from omeka_s_client.mcp import _command, main, run_server
from omeka_s_client.mcp.server import build_server
from omeka_s_client.mcp.settings import McpSettings
from omeka_s_client.testing import FakeOmeka


def settings(**options: Any) -> McpSettings:
    return McpSettings(
        url="https://example.org", key_identity="identity", key_credential="secret", **options
    )


async def test_mcp_read_tools_and_template() -> None:
    match = {"o:id": 2, "dcterms:identifier": [{"@value": "abc"}]}
    fake = FakeOmeka({"items": [{"o:id": 1}, match]})
    server = build_server(
        settings(mcp_allow_writes=False, mcp_workdir=None, mcp_max_records=1), transport=fake
    )
    async with Client(server) as client:
        server_info = client.server_info
        assert server_info is not None and server_info.name == "Omeka S Client"
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {
            "omeka_list_api_resources",
            "omeka_get_record",
            "omeka_list_records_page",
            "omeka_find_records_by_property",
            "omeka_list_all_records",
        }
        assert set(tools["omeka_get_record"].input_schema["required"]) == {
            "resource",
            "record_id",
        }
        assert set(tools["omeka_find_records_by_property"].input_schema["required"]) == {
            "resource",
            "property",
            "comparison",
        }
        assert tools["omeka_get_record"].annotations.read_only_hint
        assert tools["omeka_get_record"].annotations.idempotent_hint
        assert (await client.call_tool("omeka_list_api_resources")).data == {
            "records": [{"o:id": "items"}],
        }
        result = await client.call_tool("omeka_get_record", {"resource": "items", "record_id": 1})
        assert result.structured_content == {"o:id": 1}
        page = (
            await client.call_tool(
                "omeka_list_records_page",
                {
                    "resource": "items",
                    "page": 2,
                    "per_page": 1,
                    "filters": [["tag", "a"], ["tag", "b"]],
                },
            )
        ).data
        assert page["records"] == [match] and page["total"] == 2
        assert not page["has_next"]
        found = await client.call_tool(
            "omeka_find_records_by_property",
            {
                "resource": "items",
                "property": "dcterms:identifier",
                "comparison": "eq",
                "value": "abc",
            },
        )
        assert found.data == {"records": [match]}
        property_query = parse_qs(urlsplit(fake.requests[-1].url).query)
        assert property_query["property[0][type]"] == ["eq"]
        assert property_query["property[0][text]"] == ["abc"]
        (resource,) = await client.read_resource("omeka://items/1")
        assert isinstance(resource, TextResourceContents)
        assert json.loads(resource.text) == {"o:id": 1}
        with pytest.raises(ToolError, match="limit"):
            await client.call_tool("omeka_list_all_records", {"resource": "items"})
        with pytest.raises(ToolError):
            await client.call_tool(
                "omeka_list_records_page", {"resource": "items", "per_page": 101}
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "omeka_create_record", {"resource": "items", "payload": {}, "confirm": True}
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "omeka_delete_record", {"resource": "items", "record_id": 1, "confirm": True}
            )
        assert all(request.method == "GET" for request in fake.requests)
        with pytest.raises(ToolError) as error:
            await client.call_tool("omeka_get_record", {"resource": "items", "record_id": 99})
        assert "404" in str(error.value)
        assert "secret" not in str(error.value) and "identity" not in str(error.value)


async def test_mcp_local_paths_and_confirmed_writes(tmp_path: Path) -> None:
    fake = FakeOmeka(
        {"item_sets": [{"o:id": 7}], "items": [], "media": []}, files={"/f": b"sample"}
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink = workdir / "outside-link"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError:
        symlink = None
    server = build_server(settings(mcp_allow_writes=True, mcp_workdir=workdir), transport=fake)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {
            "omeka_list_api_resources",
            "omeka_get_record",
            "omeka_list_records_page",
            "omeka_find_records_by_property",
            "omeka_list_all_records",
            "omeka_capture_snapshot",
            "omeka_download_file",
            "omeka_create_record",
            "omeka_patch_record",
            "omeka_delete_record",
        }
        assert set(tools["omeka_capture_snapshot"].input_schema["required"]) == {
            "item_set_id",
            "directory",
        }
        assert set(tools["omeka_download_file"].input_schema["required"]) == {
            "url",
            "destination",
        }
        assert set(tools["omeka_patch_record"].input_schema["required"]) == {
            "resource",
            "record_id",
            "payload",
        }
        assert tools["omeka_patch_record"].annotations.destructive_hint
        assert not tools["omeka_create_record"].annotations.idempotent_hint
        assert not tools["omeka_download_file"].annotations.destructive_hint

        args = {"resource": "items", "payload": {"o:item_set": [{"o:id": 7}]}}
        result = await client.call_tool("omeka_create_record", args)
        assert result.data["sent"] is False and not fake.requests
        with pytest.raises(ToolError):
            await client.call_tool("omeka_create_record", {**args, "confirm": "true"})
        assert not fake.requests
        result = await client.call_tool("omeka_create_record", {**args, "confirm": True})
        assert result.data["record"]["o:id"] == 1 and len(fake.requests) == 1

        patch = {
            "resource": "items",
            "record_id": 1,
            "payload": {"dcterms:title": [{"@value": "valid"}]},
        }
        result = await client.call_tool("omeka_patch_record", patch)
        assert not result.data["sent"] and len(fake.requests) == 1
        assert result.data["preview"]["id"] == 1
        with pytest.raises(ToolError, match="replace_rdf_values"):
            await client.call_tool("omeka_patch_record", {**patch, "confirm": True})
        result = await client.call_tool(
            "omeka_patch_record",
            {**patch, "confirm": True, "replace_rdf_values": True},
        )
        assert result.data["record"]["dcterms:title"][0]["@value"] == "valid"
        assert len(fake.requests) == 2

        listing = await client.call_tool(
            "omeka_list_all_records", {"resource": "items", "verify": True}
        )
        assert len(listing.data["records"]) == 1
        snapshot = await client.call_tool(
            "omeka_capture_snapshot", {"item_set_id": 7, "directory": "new"}
        )
        assert snapshot.data["name"] == "new"
        assert snapshot.data["items_count"] == 1 and (workdir / "new" / "snapshot.json").exists()
        download = await client.call_tool(
            "omeka_download_file", {"url": "https://cdn.example.org/f", "destination": "f"}
        )
        assert download.data["name"] == "f"
        assert download.data["size"] == 6 and (workdir / "f").read_bytes() == b"sample"

        names = ["../escape", "a/../../escape", "/rooted", "C:\\bad", ".", ""]
        if symlink is not None:
            names.append("outside-link/escape")
        before = len(fake.requests)
        for name in names:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "omeka_download_file", {"url": "https://example.org/f", "destination": name}
                )
            with pytest.raises(ToolError):
                await client.call_tool(
                    "omeka_create_record", {**args, "confirm": True, "files": [name]}
                )
        assert not list(outside.iterdir()) and len(fake.requests) == before

        with pytest.raises(ToolError, match="one file"):
            await client.call_tool(
                "omeka_create_record", {"resource": "assets", "payload": {}, "files": ["f", "f"]}
            )
        with pytest.raises(ToolError, match="input"):
            await client.call_tool(
                "omeka_create_record",
                {
                    "resource": "items",
                    "payload": {"file_index": 1},
                    "files": ["f"],
                    "confirm": True,
                },
            )


async def test_mcp_delete_requires_strict_confirmation() -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}]})
    server = build_server(settings(mcp_allow_writes=True), transport=fake)
    name = "omeka_delete_record"
    target = {"resource": "items", "record_id": 1}
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == name)
        assert set(tool.input_schema["required"]) == {"resource", "record_id"}
        assert tool.input_schema["properties"]["confirm"]["default"] is False
        assert tool.annotations.destructive_hint and not tool.annotations.read_only_hint

        for args in (target, {**target, "confirm": False}):
            preview = await client.call_tool(name, args)
            assert preview.data == {
                "sent": False,
                "preview": {
                    "method": "DELETE",
                    "resource": "items",
                    "id": 1,
                    "installation_url": "https://example.org",
                },
            }
        for overrides in (
            {"confirm": "true"},
            {"confirm": 1},
            {"record_id": 0, "confirm": True},
            {"record_id": True, "confirm": True},
            {"resource": "items/1"},
        ):
            with pytest.raises(ToolError):
                await client.call_tool(name, {**target, **overrides})
        assert not fake.requests

        confirmed = {**target, "confirm": True}
        deleted = await client.call_tool(name, confirmed)
        assert deleted.data == {"sent": True, "resource": "items", "id": 1}
        assert fake.records["items"] == [{"o:id": 2}]
        assert [request.method for request in fake.requests] == ["DELETE"]
        with pytest.raises(ToolError, match="404"):
            await client.call_tool(name, confirmed)


async def test_mcp_file_uploads_use_workspace(tmp_path: Path) -> None:
    requests: list[TransportRequest] = []
    (tmp_path / "test.png").write_bytes(b"image-content")

    def transport(request: TransportRequest) -> TransportResponse:
        requests.append(request)
        return TransportResponse(201, content=b'{"o:id":3}')

    async with Client(
        build_server(
            settings(mcp_allow_writes=True, mcp_workdir=tmp_path),
            transport=transport,
        )
    ) as client:
        for resource in ("assets", "items"):
            result = await client.call_tool(
                "omeka_create_record",
                {
                    "resource": resource,
                    "payload": {},
                    "files": ["test.png"],
                    "confirm": True,
                },
            )
            assert result.data["sent"]
    assert b'name="file"; filename="test.png"' in requests[0].content
    assert b'name="file[0]"; filename="test.png"' in requests[1].content
    assert all(b"image-content" in request.content for request in requests)


async def test_mcp_workdir_required_for_upload() -> None:
    async with Client(build_server(settings(mcp_allow_writes=True, mcp_workdir=None))) as client:
        with pytest.raises(ToolError, match="Set OMEKA_MCP_WORKDIR"):
            await client.call_tool(
                "omeka_create_record",
                {
                    "resource": "assets",
                    "payload": {},
                    "files": ["f"],
                    "confirm": True,
                },
            )


def test_mcp_entry_points(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []

    def capture(_: FastMCP, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(FastMCP, "run", capture)
    monkeypatch.setenv("OMEKA_URL", "https://example.org")
    run_server(McpSettings(), "stdio", "127.0.0.1", 8000)
    assert calls[-1] == {"transport": "stdio", "show_banner": False}
    result = CliRunner().invoke(build_app(), ["mcp", "--transport", "http", "--port", "8005"])
    assert result.exit_code == 0
    assert "no authentication" in result.stderr
    assert calls[-1] == {
        "transport": "http",
        "host": "127.0.0.1",
        "port": 8005,
        "show_banner": False,
    }
    monkeypatch.setattr(sys, "argv", ["omeka-s-mcp"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    with pytest.raises(typer.Exit):
        _command(transport="invalid")
    assert "transport" in capsys.readouterr().err
    monkeypatch.setenv("OMEKA_TIMEOUT", "very-secret")
    with pytest.raises(typer.Exit):
        _command()
    assert "very-secret" not in capsys.readouterr().err


async def test_visibility_cannot_override_write_gate() -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}]})
    server = build_server(settings(mcp_allow_writes=False), transport=fake)
    server.enable(tags={"write"})
    async with Client(server) as client:
        for name, extra in (
            ("omeka_create_record", {"payload": {}}),
            ("omeka_patch_record", {"record_id": 1, "payload": {}}),
            ("omeka_delete_record", {"record_id": 1}),
        ):
            with pytest.raises(ToolError, match="write tools are disabled"):
                await client.call_tool(
                    name,
                    {
                        "resource": "items",
                        "confirm": True,
                        **extra,
                    },
                )
    assert not fake.requests


def test_mcp_path_resolution_errors_are_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omeka_s_client.mcp.server import _workspace_path

    def fail(_: Path) -> Path:
        raise OSError("private path")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", fail)
        with pytest.raises(ToolError, match="Cannot resolve") as error:
            _workspace_path(tmp_path, "inside")
    assert "private path" not in str(error.value)
    with pytest.raises(ToolError, match="relative path"):
        _workspace_path(tmp_path, r"folder\..\file")


def test_mcp_requires_an_existing_workdir(tmp_path: Path) -> None:
    from omeka_s_client import ConfigurationError

    file = tmp_path / "file"
    file.touch()
    for path in (file, tmp_path / "missing"):
        with pytest.raises(ConfigurationError, match="existing directory"):
            build_server(settings(mcp_workdir=path))

    from omeka_s_client.mcp.server import _workspace_path

    with pytest.raises(ToolError, match="leaves"):
        _workspace_path(tmp_path / "noncanonical" / "..", "file")
