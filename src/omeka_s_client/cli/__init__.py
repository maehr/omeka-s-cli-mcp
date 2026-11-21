"""Typer commands for the Omeka S client."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from pydantic import StrictInt, TypeAdapter, ValidationError
from pydantic_settings import SettingsError
from typer.core import TyperCommand, TyperOption

from .. import (
    ConfigurationError,
    IncompleteListingError,
    OmekaClient,
    OmekaError,
    Record,
    Snapshot,
    Transport,
    Upload,
    WriteOutcomeUnknownError,
    capture_snapshot,
    property_filter,
    property_filters,
    read_snapshot,
    write_snapshot,
)
from .._urls import validate_resource_name
from ..snapshots import Variant
from .settings import OmekaSettings

_S = TypeVar("_S", bound=OmekaSettings)
_ID = Annotated[int, typer.Argument(min=1)]
_PER_PAGE = Annotated[int, typer.Option(min=1)]
_FILTERS = Annotated[list[str] | None, typer.Option("--filter", metavar="KEY=VALUE")]
_PAYLOAD = Annotated[Path, typer.Option("--payload", exists=True, dir_okay=False)]
_RECORD = TypeAdapter(Record)
_IDS = TypeAdapter(list[StrictInt])


def _identity(value: Any) -> Any:
    return value


class _PropertyCommand(TyperCommand):
    # Typer supports repeatable options and tuple options separately. Set the
    # option arity here to allow the repeatable three-value form.
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for parameter in self.params:
            if isinstance(parameter, TyperOption) and parameter.name == "properties":
                parameter.nargs = 3


@dataclass(slots=True)
class _Options:
    transport: Transport | None
    url: str | None
    key_identity: str | None
    key_credential_file: Path | None
    env_file: Path | None

    def settings(self, cls: type[_S]) -> _S:
        options: dict[str, Any] = {}
        if self.url is not None:
            options["url"] = self.url
        if self.key_identity is not None:
            options["key_identity"] = self.key_identity
        if self.key_credential_file is not None:
            options["key_credential"] = self.key_credential_file.read_text(encoding="utf-8").rstrip(
                "\r\n"
            )
        return cls(_env_file=self.env_file, _env_file_encoding="utf-8", **options)

    def client(self) -> OmekaClient:
        return self.settings(OmekaSettings).open_client(transport=self.transport)


@contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except (ValidationError, SettingsError):
        _exit("Invalid configuration or JSON input.", 2)
    except ConfigurationError as error:
        _exit(str(error), 2)
    except IncompleteListingError as error:
        _exit(str(error), 3)
    except WriteOutcomeUnknownError as error:
        _exit(str(error), 4)
    except OmekaError as error:
        _exit(str(error), 1)
    except (ValueError, OSError):
        _exit("Invalid argument or file input.", 2)


def _exit(message: str, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _output(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _filters(values: list[str] | None) -> list[tuple[str, str]]:
    pairs = []
    for filter_value in values or ():
        key, separator, value = filter_value.partition("=")
        if not key or not separator:
            _exit("Use KEY=VALUE for each filter.", 2)
        pairs.append((key, value))
    return pairs


def _options(ctx: typer.Context) -> _Options:
    return ctx.find_root().obj


def build_app(*, transport: Transport | None = None) -> typer.Typer:
    """Build the CLI with an optional test transport.

    >>> build_app() is not None
    True
    """
    app = typer.Typer(help="Read and update Omeka S records.", no_args_is_help=True)
    snapshot_app = typer.Typer(help="Capture and check metadata snapshots.", no_args_is_help=True)
    app.add_typer(snapshot_app, name="snapshot")

    @app.callback()
    def configure(
        ctx: typer.Context,
        url: Annotated[str | None, typer.Option(help="Omeka S installation URL.")] = None,
        key_identity: Annotated[str | None, typer.Option(help="Omeka API key identity.")] = None,
        key_credential_file: Annotated[
            Path | None, typer.Option(exists=True, dir_okay=False, help="File with the credential.")
        ] = None,
        env_file: Annotated[
            Path | None,
            typer.Option(exists=True, dir_okay=False, help="Read settings from this file."),
        ] = None,
    ) -> None:
        ctx.obj = _Options(transport, url, key_identity, key_credential_file, env_file)

    @app.command(help="List the available API resources.")
    def resources(ctx: typer.Context) -> None:
        with _errors(), _options(ctx).client() as client:
            _output(client.page("api_resources").records)

    @app.command(help="Print one record by ID.")
    def get(ctx: typer.Context, resource: str, id: _ID) -> None:
        with _errors(), _options(ctx).client() as client:
            _output(client.get(resource, id))

    @app.command("list", cls=_PropertyCommand, help="Read all pages of a resource.")
    def list_records(
        ctx: typer.Context,
        resource: str,
        filter: _FILTERS = None,
        properties: Annotated[
            list[str] | None,
            typer.Option("--property", metavar="TERM TYPE VALUE", parser=_identity),
        ] = None,
        per_page: _PER_PAGE = 50,
        verify: Annotated[bool, typer.Option("--verify")] = False,
        expected_ids: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
        jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
        output: Annotated[Path | None, typer.Option(dir_okay=False)] = None,
    ) -> None:
        with _errors(), _options(ctx).client() as client:
            conditions = [
                property_filter(term, kind, value) for term, kind, value in properties or ()
            ]
            records = client.list(
                resource,
                filters=[*_filters(filter), *property_filters(*conditions)],
                per_page=per_page,
                verify=verify,
                expected_ids=None
                if expected_ids is None
                else _IDS.validate_json(expected_ids.read_bytes()),
            )
            if jsonl:
                result = "".join(
                    json.dumps(record, ensure_ascii=False) + "\n" for record in records
                )
            else:
                result = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
            if output is None:
                typer.echo(result, nl=False)
            else:
                output.write_text(result, encoding="utf-8", newline="\n")

    @app.command(help="Print one page with its total.")
    def page(
        ctx: typer.Context,
        resource: str,
        page: Annotated[int, typer.Option(min=1)] = 1,
        per_page: _PER_PAGE = 50,
        filter: _FILTERS = None,
    ) -> None:
        with _errors(), _options(ctx).client() as client:
            _output(
                asdict(
                    client.page(resource, page=page, per_page=per_page, filters=_filters(filter))
                )
            )

    @app.command(help="Create a record from a JSON payload.")
    def create(
        ctx: typer.Context,
        resource: str,
        payload: _PAYLOAD,
        file: Annotated[
            list[Path] | None, typer.Option("--file", exists=True, dir_okay=False)
        ] = None,
        asset_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ) -> None:
        with _errors(), _options(ctx).client() as client:
            if asset_file is not None and file:
                _exit("Choose --file or --asset-file.", 2)
            record = _RECORD.validate_json(payload.read_bytes())
            files = (
                Upload(path=asset_file)
                if asset_file
                else [Upload(path=path) for path in file or ()]
            )
            if dry_run:
                _output(
                    {
                        "sent": False,
                        "method": "POST",
                        "resource": resource,
                        "payload": record,
                        "files": [str(asset_file)]
                        if asset_file
                        else [str(path) for path in file or ()],
                    }
                )
            else:
                _output(client.create(resource, record, files=files))

    @app.command(help="Update a record from a JSON payload.")
    def patch(
        ctx: typer.Context,
        resource: str,
        id: _ID,
        payload: _PAYLOAD,
        replace_rdf_values: Annotated[bool, typer.Option("--replace-rdf-values")] = False,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ) -> None:
        with _errors(), _options(ctx).client() as client:
            record = _RECORD.validate_json(payload.read_bytes())
            if dry_run:
                _output(
                    {
                        "sent": False,
                        "method": "PATCH",
                        "resource": resource,
                        "id": id,
                        "payload": record,
                        "replace_rdf_values": replace_rdf_values,
                    }
                )
            else:
                _output(client.patch(resource, id, record, replace_rdf_values=replace_rdf_values))

    @app.command(help="Preview or permanently delete one record.")
    def delete(
        ctx: typer.Context,
        resource: str,
        id: _ID,
        dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview the target.")] = False,
        confirm: Annotated[bool, typer.Option("--confirm", help="Send the request.")] = False,
    ) -> None:
        if dry_run and confirm:
            _exit("Choose --dry-run or --confirm.", 2)
        with _errors(), _options(ctx).client() as client:
            if confirm:
                client.delete(resource, id)
            else:
                validate_resource_name(resource)
            _output(
                {
                    "sent": confirm,
                    "method": "DELETE",
                    "resource": resource,
                    "id": id,
                    "installation_url": client.installation_url,
                }
            )

    @app.command(help="Download a file to a new destination.")
    def download(ctx: typer.Context, url: str, dest: Path) -> None:
        with _errors(), _options(ctx).client() as client:
            result = client.download(url, dest)
            _output({"path": str(result.path), "size": result.size, "sha256": result.sha256})

    @snapshot_app.command(help="Read an item set and write a metadata snapshot.")
    def capture(
        ctx: typer.Context,
        item_set_id: _ID,
        directory: Path,
        variant: Annotated[str, typer.Option(help="Use plain, raw, or transformed files.")] = "",
    ) -> None:
        with _errors(), _options(ctx).client() as client:
            file_variant = _variant(variant)
            snapshot = capture_snapshot(client, item_set_id)
            output = write_snapshot(directory, snapshot, variant=file_variant)
            _output({"path": str(output), **_counts(snapshot)})

    @snapshot_app.command(help="Check a local metadata snapshot.")
    def check(directory: Path) -> None:
        with _errors():
            _output(_counts(read_snapshot(directory)))

    @app.command("mcp", help="Start the Omeka S MCP server.")
    def mcp_command(
        ctx: typer.Context,
        transport: Annotated[str, typer.Option(help="Use stdio or http.")] = "stdio",
        host: str = "127.0.0.1",
        port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    ) -> None:
        from ..mcp import run_server
        from ..mcp.settings import McpSettings

        options = _options(ctx)
        with _errors():
            run_server(options.settings(McpSettings), transport, host, port, options.transport)

    return app


def _variant(value: str) -> Variant:
    if value in ("", "plain"):
        return ""
    if value == "raw":
        return "raw"
    if value == "transformed":
        return "transformed"
    raise ConfigurationError("Use plain, raw, or transformed as the snapshot variant.")


def _counts(snapshot: Snapshot) -> dict[str, int | None]:
    return {
        "item_set_id": snapshot.item_set_id,
        "items_count": len(snapshot.items),
        "media_count": len(snapshot.media),
    }


app = build_app()


def main() -> None:
    """Run the Omeka S command line."""
    app()
