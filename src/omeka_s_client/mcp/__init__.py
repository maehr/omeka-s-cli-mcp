"""Entry point for the Omeka S MCP server."""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import ValidationError
from pydantic_settings import SettingsError

from .. import ConfigurationError, Transport
from .settings import McpSettings


def run_server(
    settings: McpSettings,
    mode: str,
    host: str,
    port: int,
    transport: Transport | None = None,
) -> None:
    """Run a server on stdio or streamable HTTP."""
    if mode not in {"stdio", "http"}:
        raise ConfigurationError("Use stdio or http as the MCP transport.")
    with settings.open_client(transport=transport):
        # Validate settings before the server opens its transport.
        pass
    from .server import build_server

    server = build_server(settings, transport=transport)
    if mode == "http":
        typer.echo("Warning: the MCP HTTP transport has no authentication.", err=True)
        server.run(transport="http", host=host, port=port, show_banner=False)
    else:
        server.run(transport="stdio", show_banner=False)


def _command(
    transport: Annotated[str, typer.Option(help="Use stdio or http.")] = "stdio",
    host: str = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    try:
        run_server(McpSettings(), transport, host, port)
    except ConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    except (ValidationError, SettingsError, OSError, RuntimeError):
        typer.echo("Invalid MCP configuration or server startup failure.", err=True)
        raise typer.Exit(2) from None


def main() -> None:
    """Run the Omeka S MCP command."""
    typer.run(_command)
