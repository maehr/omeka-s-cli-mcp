# Omeka S Client

Read and update Omeka S records with Python or the command line. Use the Model Context Protocol (MCP) server to connect an MCP client.

The package supports Python 3.11 and later. The integration tests cover Omeka S 3.2.3, 4.1.1, and 4.2.1. [Compatibility](https://github.com/maehr/omeka-s-client/blob/main/docs/compatibility.md) [API coverage](https://github.com/maehr/omeka-s-client/blob/main/docs/api-coverage.md)

## Install the prototype

Activate a Python virtual environment. Install the Python library.

```sh
uv pip install git+https://github.com/maehr/omeka-s-client
```

To use the CLI and MCP server, install the optional dependencies.

```sh
uv pip install 'omeka-s-client[cli,mcp] @ git+https://github.com/maehr/omeka-s-client'
```

Use `[cli]` for the command line alone. Use `[mcp]` for the MCP server and the command line.

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

Use `OMEKA_KEY_IDENTITY` and `OMEKA_KEY_CREDENTIAL` with the command line or MCP server for authenticated access. [CLI configuration](https://github.com/maehr/omeka-s-client/blob/main/docs/cli.md)

## Connect an MCP client

`omeka-s-mcp` runs outside the Omeka installation and uses [FastMCP](https://github.com/PrefectHQ/fastmcp). Writes require a server setting and confirmation for each call. [MCP configuration](https://github.com/maehr/omeka-s-client/blob/main/docs/mcp.md)

The [Omeka McpServer module](https://github.com/omeka-s-modules/McpServer) runs in Omeka S 4.2.1 or later and supplies read-only tools.

## Documentation

- [API coverage](https://github.com/maehr/omeka-s-client/blob/main/docs/api-coverage.md): supported operations, resources, and limits.
- [Playground](https://maehr.github.io/omeka-s-client/): run the client in your browser. [Playground guide](https://github.com/maehr/omeka-s-client/blob/main/docs/playground.md)
- [Python API reference](https://maehr.github.io/omeka-s-client/api/): generated with pdoc from the public `omeka_s_client` API.
- [Python API](https://github.com/maehr/omeka-s-client/blob/main/docs/usage.md)
- [Command line](https://github.com/maehr/omeka-s-client/blob/main/docs/cli.md)
- [MCP tools](https://github.com/maehr/omeka-s-client/blob/main/docs/mcp.md)
- [Snapshot format](https://github.com/maehr/omeka-s-client/blob/main/docs/snapshot-format.md)
- [Security](https://github.com/maehr/omeka-s-client/blob/main/docs/security.md)
- [Contributing](https://github.com/maehr/omeka-s-client/blob/main/CONTRIBUTING.md)

The source code uses the [AGPL-3.0-only license](https://github.com/maehr/omeka-s-client/blob/main/LICENSE).
