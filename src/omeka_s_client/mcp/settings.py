"""Configuration for the Omeka S MCP server."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from ..cli.settings import OmekaSettings


class McpSettings(OmekaSettings):
    """Read the Omeka and MCP configuration.

    >>> McpSettings(mcp_allow_writes=False).mcp_allow_writes
    False
    """

    mcp_allow_writes: bool = False
    mcp_max_records: int = Field(default=500, gt=0)
    mcp_workdir: Path | None = None
