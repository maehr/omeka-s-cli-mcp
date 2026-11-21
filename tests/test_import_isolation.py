from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


def test_library_import_only_uses_library_dependencies() -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            dedent("""
            import sys
            from importlib.abc import MetaPathFinder

            class BlockTools(MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".")[0] in {"typer", "fastmcp", "pydantic_settings", "mcp"}:
                        raise ImportError(fullname)
                    return None

            sys.meta_path.insert(0, BlockTools())
            from omeka_s_client import OmekaClient, Snapshot
            from omeka_s_client.testing import FakeOmeka
            with OmekaClient("https://example.org", transport=FakeOmeka()) as client:
                assert client.installation_url == "https://example.org"
            assert Snapshot("", None, [], []).item_set_id is None
            """),
        ],
        check=True,
    )


@pytest.mark.parametrize(
    ("entry", "module", "extra"),
    [
        ("cli", "omeka_s_client.cli", "cli"),
        ("mcp", "omeka_s_client.mcp", "mcp"),
    ],
)
def test_optional_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
    module: str,
    extra: str,
) -> None:
    from importlib import import_module

    from omeka_s_client import _entry_points

    command = getattr(_entry_points, entry)
    calls: list[str] = []
    monkeypatch.setattr(import_module(module), "main", lambda: calls.append(entry))
    command()
    assert calls == [entry]

    from importlib.util import find_spec

    missing = "typer" if extra == "cli" else "fastmcp"
    monkeypatch.setattr(
        _entry_points, "find_spec", lambda name: None if name == missing else find_spec(name)
    )
    with pytest.raises(SystemExit, match=rf"Install omeka-s-client\[{extra}\]"):
        command()
    assert calls == [entry]
