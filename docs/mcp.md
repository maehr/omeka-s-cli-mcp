# Omeka S Client MCP server

Install Omeka S Client with the `[mcp]` extra in a virtual environment. [Installation](../README.md#install-the-prototype)

Replace the example executable path with the absolute path to your `omeka-s-mcp` executable. On Windows, find `omeka-s-mcp.exe` in the virtual environment's `Scripts` directory.

## Claude Code

Set `OMEKA_URL` to your Omeka installation URL.

```sh
claude mcp add --transport stdio omeka-s --env OMEKA_URL=https://example.org -- \
  /path/to/venv/bin/omeka-s-mcp
```

For authenticated access, set both Omeka key variables in the client environment. Keep the credential in a private configuration file.

## Claude Desktop

Set each configuration variable in the `env` object. Claude Desktop starts the server with its own environment.

```json
{
  "mcpServers": {
    "omeka-s": {
      "command": "/path/to/venv/bin/omeka-s-mcp",
      "env": {"OMEKA_URL": "https://example.org"}
    }
  }
}
```

The server uses standard input and output by default. The `omeka-s mcp` command starts the same server. Both commands read `OMEKA_URL`, `OMEKA_KEY_IDENTITY`, `OMEKA_KEY_CREDENTIAL`, and `OMEKA_TIMEOUT`.

## Tools

| Tool | Operation |
| --- | --- |
| `omeka_list_api_resources` | Read available resources |
| `omeka_get_record` | Read a record by ID |
| `omeka_list_records_page` | Read one page, with up to 100 requested records |
| `omeka_find_records_by_property` | Read by property term or ID |
| `omeka_list_all_records` | Read a listing up to `OMEKA_MCP_MAX_RECORDS`, which defaults to 500 |
| `omeka_capture_snapshot` | Write a snapshot in the work directory |
| `omeka_download_file` | Download a file to the work directory |
| `omeka_create_record` | Preview or create an Omeka record |
| `omeka_patch_record` | Preview or update an Omeka record |
| `omeka_delete_record` | Preview or permanently delete an Omeka record |

`omeka_list_api_resources` reads only the first page of `api_resources`, with up to 50 resources. The list can be incomplete on an installation with many modules.

The tools use the Python client. The same API limits apply: one-segment resource names, positive integer IDs, and no `PUT`. [API coverage](api-coverage.md)

`omeka_capture_snapshot` saves only the records that the configured keys can read. Without keys, it saves only public records. It does not save the original files. [Snapshot format](snapshot-format.md)

Use the resource template `omeka://{resource}/{id}` to read a record as an MCP resource.

Set `OMEKA_MCP_ALLOW_WRITES=true` to enable the Omeka write tools. Review the preview. Set `confirm=true` to send the write request. To replace RDF values, also set `replace_rdf_values=true`.

Set `OMEKA_MCP_WORKDIR` to an existing private directory to enable snapshot capture and downloads. Use paths relative to this directory for all local tools and uploads. Use a directory under your control. [Security](security.md)

Use `omeka-s-mcp --transport http` for HTTP transport. The default endpoint is `http://127.0.0.1:8000/mcp`. Keep the HTTP binding on loopback because the transport has no authentication.

[Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)

## Delete a record

**Caution.** Check the installation, resource, and ID in the preview. Omeka S permanently deletes the record when you confirm.

Enable the Omeka write tools before you call `omeka_delete_record`. To preview the request, pass `{"resource": "items", "record_id": 123}`. Add `"confirm": true` to the call arguments to send the request. Check the record before you repeat a deletion after an unknown outcome or a server error. [Write errors](security.md#writes)

## Migrate existing MCP clients

The server now reports the name **Omeka S Client**. Update tool calls and allowlists to use the names below. Replace each argument shown in the last column.

| Previous tool | Current tool | Argument change |
| --- | --- | --- |
| `omeka_api_resources` | `omeka_list_api_resources` | |
| `omeka_get` | `omeka_get_record` | `id` becomes `record_id` |
| `omeka_search` | `omeka_list_records_page` | |
| `omeka_find_by_property` | `omeka_find_records_by_property` | `type` becomes `comparison` |
| `omeka_list_all` | `omeka_list_all_records` | |
| `omeka_capture_snapshot` | `omeka_capture_snapshot` | `name` becomes `directory` |
| `omeka_download` | `omeka_download_file` | `name` becomes `destination` |
| `omeka_create` | `omeka_create_record` | |
| `omeka_patch` | `omeka_patch_record` | `id` becomes `record_id` |

Reconnect the MCP client to refresh its tool list.
