# MCP server

Install the `[mcp]` extra. [Installation](../README.md#install-the-prototype)

Run `omeka-s-mcp` to start the server on standard input and output. `omeka-s mcp` starts the same server. Both commands read the `OMEKA_URL`, `OMEKA_KEY_IDENTITY`, `OMEKA_KEY_CREDENTIAL`, and `OMEKA_TIMEOUT` settings.

## Claude Code

Use the installation URL in your command. For a public installation, add this server.

```sh
claude mcp add --transport stdio omeka-s --env OMEKA_URL=https://example.org -- \
  uvx --from 'omeka-s-client[mcp] @ git+https://github.com/maehr/omeka-s-cli-mcp' omeka-s-mcp
```

For authenticated access, configure both Omeka key variables in the client's environment settings. Use a private client configuration file for the credential.

## Claude Desktop

Set each configuration variable in the `env` object. Claude Desktop starts the server with its own environment.

```json
{
  "mcpServers": {
    "omeka-s": {
      "command": "uvx",
      "args": ["--from", "omeka-s-client[mcp] @ git+https://github.com/maehr/omeka-s-cli-mcp", "omeka-s-mcp"],
      "env": {"OMEKA_URL": "https://example.org"}
    }
  }
}
```

If the client cannot find `uvx`, use its absolute path.

## Tools

| Tool | Operation |
| --- | --- |
| `omeka_api_resources` | Read available resources |
| `omeka_get` | Read a record by ID |
| `omeka_search` | Read one page, with up to 100 requested records |
| `omeka_find_by_property` | Read by property term or ID |
| `omeka_list_all` | Read a listing up to `OMEKA_MCP_MAX_RECORDS`, which defaults to 500 |
| `omeka_capture_snapshot` | Write a snapshot in the work directory |
| `omeka_download` | Download a file to the work directory |
| `omeka_create` | Preview or create an Omeka record |
| `omeka_patch` | Preview or update an Omeka record |

Use the resource template `omeka://{resource}/{id}` to read a record as an MCP resource.

Set `OMEKA_MCP_ALLOW_WRITES=true` to enable the two Omeka write tools. Review the preview. Set `confirm=true` to send the write request. To replace RDF values, also set `replace_rdf_values=true`.

Set `OMEKA_MCP_WORKDIR` to an existing private directory to enable snapshot capture and downloads. Use paths relative to this directory for all local tools and uploads. Use a directory under your control. [Security](security.md)

Use `omeka-s-mcp --transport http` for HTTP transport. The default endpoint is `http://127.0.0.1:8000/mcp`. Keep the HTTP binding on loopback because the transport has no authentication.

[Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)
