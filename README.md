# Omeka S client

Read and update Omeka S records with Python or the command line. Use the Model Context Protocol (MCP) server to connect an MCP client.

The package supports Python 3.11 and later. The integration tests cover Omeka S 3.2.3, 4.1.1, and 4.2.1. [Compatibility](docs/compatibility.md)

## Install the prototype

Activate a Python virtual environment. Install the package from GitHub.

```sh
uv pip install git+https://github.com/maehr/omeka-s-cli-mcp
```

The package installs the `omeka_s_client` library, the `omeka-s` command, and the `omeka-s-mcp` server.

## Read records

Use the URL of your Omeka S installation. Public API reads can use this example.

```python
from omeka_s_client import OmekaClient

with OmekaClient("https://example.org/collection") as client:
    item = client.get("items", 1)
    items = client.list("items", filters={"item_set_id": 7}, verify=True)
```

```sh
omeka-s --url https://example.org/collection page items --per-page 10
```

Use `OMEKA_KEY_IDENTITY` and `OMEKA_KEY_CREDENTIAL` with the command line or MCP server for authenticated access. [CLI configuration](docs/cli.md)

## Connect an MCP client

`omeka-s-mcp` runs outside the Omeka installation and uses [FastMCP](https://github.com/PrefectHQ/fastmcp). Writes require a server setting and confirmation for each call. [MCP configuration](docs/mcp.md)

The [Omeka McpServer module](https://github.com/omeka-s-modules/McpServer) runs in Omeka S 4.2.1 or later and supplies read-only tools.

## Documentation

- [Python API](docs/usage.md)
- [Command line](docs/cli.md)
- [MCP tools](docs/mcp.md)
- [Snapshot format](docs/snapshot-format.md)
- [Security](docs/security.md)
- [Contributing](CONTRIBUTING.md)

The source code uses the [AGPL-3.0-only license](LICENSE).
