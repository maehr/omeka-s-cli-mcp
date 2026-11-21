"""Entry points for the optional tools."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Literal

from .errors import ConfigurationError


def require_tool_extra(extra: Literal["cli", "mcp"]) -> None:
    modules = ("typer", "pydantic_settings")
    if extra == "mcp":
        modules += ("fastmcp",)
    if any(find_spec(module) is None for module in modules):
        raise ConfigurationError(f"Install omeka-s-client[{extra}] to use this command.")


def cli() -> None:
    try:
        require_tool_extra("cli")
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
    from .cli import main

    main()


def mcp() -> None:
    try:
        require_tool_extra("mcp")
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
    from .mcp import main

    main()
