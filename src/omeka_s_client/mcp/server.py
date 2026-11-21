"""FastMCP tools that use the public Omeka client API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool

from .. import (
    ConfigurationError,
    OmekaClient,
    OmekaError,
    QueryParams,
    Record,
    Transport,
    Upload,
    capture_snapshot,
    property_filter,
    property_filters,
    write_snapshot,
)
from ..types import Scalar
from .settings import McpSettings

ReadFilters = dict[str, Scalar | list[Scalar]] | list[tuple[str, Scalar]]
Positive = Annotated[int, Field(gt=0, strict=True)]
PerPage = Annotated[int, Field(gt=0, le=100, strict=True)]


@contextmanager
def _api(ctx: Context) -> Generator[OmekaClient]:
    try:
        yield ctx.lifespan_context["omeka"]
    except OmekaError as error:
        raise ToolError(str(error)) from None
    except ValueError:
        raise ToolError("Invalid Omeka request input.") from None


def _workspace_path(root: Path | None, name: str) -> Path:
    if root is None:
        raise ToolError("Set OMEKA_MCP_WORKDIR to use local files.")
    candidate = Path(name)
    windows = PureWindowsPath(name)
    if (
        not candidate.parts
        or candidate.is_absolute()
        or windows.anchor
        or ".." in candidate.parts
        or ".." in windows.parts
    ):
        raise ToolError("Use a relative path inside OMEKA_MCP_WORKDIR.")
    try:
        resolved = (root / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        raise ToolError("Cannot resolve the path in OMEKA_MCP_WORKDIR.") from None
    if resolved == root or not resolved.is_relative_to(root):
        raise ToolError("The path leaves OMEKA_MCP_WORKDIR.")
    return resolved


def _workdir(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        directory = path.resolve(strict=True)
        if directory.is_dir():
            return directory
    except (OSError, RuntimeError, ValueError):
        pass
    raise ConfigurationError("OMEKA_MCP_WORKDIR must be an existing directory.") from None


def build_server(settings: McpSettings, *, transport: Transport | None = None) -> FastMCP:
    """Build a FastMCP server with a client shared by its tools.

    >>> build_server(McpSettings(url="https://example.org")).name
    'Omeka S Client'
    """
    root = _workdir(settings.mcp_workdir)
    allow_writes = settings.mcp_allow_writes
    max_records = settings.mcp_max_records

    @lifespan
    async def shared_client(_: FastMCP) -> AsyncIterator[dict[str, OmekaClient]]:
        with settings.open_client(transport=transport) as client:
            yield {"omeka": client}

    server = FastMCP("Omeka S Client", lifespan=shared_client, mask_error_details=True)
    read = ToolAnnotations(read_only_hint=True)
    local = ToolAnnotations(destructive_hint=False, idempotent_hint=False)

    @server.tool(tags={"read"}, annotations=read)
    def omeka_list_api_resources(ctx: Context) -> dict[str, list[Record]]:
        """Read the API resource list."""
        with _api(ctx) as client:
            return {"records": client.page("api_resources").records}

    @server.tool(
        tags={"read"}, annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True)
    )
    def omeka_get_record(ctx: Context, resource: str, record_id: Positive) -> Record:
        """Read a record by ID."""
        with _api(ctx) as client:
            return client.get(resource, record_id)

    @server.tool(tags={"read"}, annotations=read)
    def omeka_list_records_page(
        ctx: Context,
        resource: str,
        filters: ReadFilters | None = None,
        page: Positive = 1,
        per_page: PerPage = 50,
    ) -> dict[str, Any]:
        """Read one page of records with optional filters."""
        query: QueryParams | None = filters
        with _api(ctx) as client:
            return asdict(client.page(resource, filters=query, page=page, per_page=per_page))

    @server.tool(tags={"read"}, annotations=read)
    def omeka_find_records_by_property(
        ctx: Context,
        resource: str,
        property: str | int,
        comparison: str,
        value: str | int | None = None,
    ) -> dict[str, list[Record]]:
        """Find records with an Omeka property filter."""
        filters = property_filters(property_filter(property, comparison, value))
        with _api(ctx) as client:
            return {"records": client.list(resource, filters=filters)}

    @server.tool(tags={"read"}, annotations=read)
    def omeka_list_all_records(
        ctx: Context, resource: str, filters: ReadFilters | None = None, verify: bool = False
    ) -> dict[str, list[Record]]:
        """Read all pages up to the server's record limit."""
        query: QueryParams | None = filters
        with _api(ctx) as client:
            records = client.list(
                resource,
                filters=query,
                verify=verify,
                max_records=max_records,
                per_page=min(50, max_records),
            )
        return {"records": records}

    @server.tool(tags={"local-write"}, annotations=local)
    def omeka_capture_snapshot(
        ctx: Context, item_set_id: Positive, directory: str
    ) -> dict[str, Any]:
        """Capture an item set in a new snapshot directory."""
        destination = _workspace_path(root, directory)
        with _api(ctx) as client:
            snapshot = capture_snapshot(client, item_set_id)
            write_snapshot(destination, snapshot)
        return {
            "name": directory,
            "item_set_id": snapshot.item_set_id,
            "items_count": len(snapshot.items),
            "media_count": len(snapshot.media),
        }

    @server.tool(tags={"local-write"}, annotations=local)
    def omeka_download_file(ctx: Context, url: str, destination: str) -> dict[str, Any]:
        """Download a file to a new path in the work directory."""
        path = _workspace_path(root, destination)
        with _api(ctx) as client:
            result = client.download(url, path)
        return {"name": destination, "size": result.size, "sha256": result.sha256}

    @server.tool(
        tags={"write"},
        annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False),
    )
    def omeka_create_record(
        ctx: Context,
        resource: str,
        payload: Record,
        files: list[str] | None = None,
        confirm: StrictBool = False,
    ) -> dict[str, Any]:
        """Preview or create a record. Set confirm to send the request."""
        if not allow_writes:
            raise ToolError("Omeka write tools are disabled.")
        uploads = [Upload(path=_workspace_path(root, name)) for name in files or ()]
        asset_upload = resource == "assets" and bool(uploads)
        if asset_upload and len(uploads) != 1:
            raise ToolError("Asset creation accepts one file.")
        if not confirm:
            return {
                "sent": False,
                "preview": {
                    "resource": resource,
                    "payload": payload,
                    "files": files or [],
                },
            }
        with _api(ctx) as client:
            return {
                "sent": True,
                "record": client.create(
                    resource, payload, files=uploads[0] if asset_upload else uploads
                ),
            }

    @server.tool(
        tags={"write"}, annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=False)
    )
    def omeka_patch_record(
        ctx: Context,
        resource: str,
        record_id: Positive,
        payload: Record,
        replace_rdf_values: StrictBool = False,
        confirm: StrictBool = False,
    ) -> dict[str, Any]:
        """Preview or update a record. Set confirm to send the request."""
        if not allow_writes:
            raise ToolError("Omeka write tools are disabled.")
        if not confirm:
            return {
                "sent": False,
                "preview": {
                    "resource": resource,
                    "id": record_id,
                    "payload": payload,
                    "replace_rdf_values": replace_rdf_values,
                },
            }
        with _api(ctx) as client:
            return {
                "sent": True,
                "record": client.patch(
                    resource, record_id, payload, replace_rdf_values=replace_rdf_values
                ),
            }

    @server.resource("omeka://{resource}/{id}", mime_type="application/json", tags={"read"})
    def omeka_record(ctx: Context, resource: str, id: int) -> Record:
        """Read an Omeka record as an MCP resource."""
        return omeka_get_record(ctx, resource, id)

    if not allow_writes:
        server.disable(tags={"write"})
    if root is None:
        server.disable(tags={"local-write"})
    return server
