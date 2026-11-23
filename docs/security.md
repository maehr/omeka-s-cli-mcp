# Security

Use HTTPS for a remote Omeka S installation. Supply both API keys for authenticated access. Omeka S receives the keys as query parameters. Keep API URLs with keys out of web server and proxy logs.

The client adds its keys only under the configured API root. It replaces keys in API links and restricts redirects to that root. Downloads use a separate HTTP client and remove keys from file URLs at each redirect.

## Playground

The playground loads Pyodide from jsDelivr without Subresource Integrity. `*.github.io` is one origin that the owner's project pages share, so the playground stores no keys.

## Writes

The client sends each write once. A connection failure before the send reports that it did not send the request. If the response is lost, the write outcome is unknown. A server can apply a write even if it sends a 5xx response. Check Omeka S before you send the same write again.

## Local files

Choose a private parent directory for downloads and snapshots. Downloads publish with a hard link when the file system supports it. If hard links are unavailable, the client checks for an existing file before replacing the destination with the temporary file. A competing process can create a file between the check and the replacement. Use unique names when processes share a parent directory.

Restrict access to `OMEKA_MCP_WORKDIR`. A process with access to modify this directory can change its entries between path validation and use.

[Report a security issue](../SECURITY.md)
