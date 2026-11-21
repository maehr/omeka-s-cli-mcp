from __future__ import annotations

import subprocess
import sys
from textwrap import dedent


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
