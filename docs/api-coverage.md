# API coverage

This page tells you which parts of the Omeka S REST API the client supports. It also tells you the limits. The statements come from the source code and the tests. [Omeka S REST API](https://omeka.org/s/docs/developer/api/rest_api/)

## Generic access and tested resources

The client gives generic access to an API resource collection by name. For example, `items`, `item_sets`, `media`, `assets`, `properties`, or a resource that a module adds. The client does not have a separate method or schema for each resource.

The tests show specific functions only for some resources:

| Resource | Tested function |
| --- | --- |
| `items` | Read, page, list, verified list, property filters, create, patch, RDF replacement, delete |
| `item_sets` | Read, create, snapshot capture |
| `media` | List by parent item, multipart upload with an item, file download, snapshot capture |
| `assets` | Multipart upload |
| `api_resources` | Resource discovery |

The client does not claim complete create, read, update, and delete support for each resource. A resource can accept a request from the client and still reject it on the server.

## Operation patterns

The Omeka S REST API uses six common operation patterns. The client exposes five of them.

| Pattern | HTTP request | Client method |
| --- | --- | --- |
| Read a collection | `GET /api/{resource}` | `page`, `list` |
| Read a record | `GET /api/{resource}/{id}` | `get` |
| Create a record | `POST /api/{resource}` | `create` |
| Update part of a record | `PATCH /api/{resource}/{id}` | `patch` |
| Delete a record | `DELETE /api/{resource}/{id}` | `delete` |
| Replace a record | `PUT /api/{resource}/{id}` | Not available |

"Five of six" counts operation patterns. It is not a percentage of the full API.

## Limits

- A record method needs a positive integer ID.
- A resource name must be one path segment. It can contain only letters, digits, `_`, and `-`.
- The client cannot send a request to a nested path or a custom path.
- Multipart uploads work only with `create`. `patch` sends JSON only.
- Records are JSON-LD dictionaries. The client does not validate a record against a resource schema.
- The client reads only JSON responses. It has no async client.
- `download` reads a file URL. It writes the file to a new local path.

## Permissions and modules

The API keys, the user role, and the server settings decide which records the client can read or change. An anonymous client reads only public records.

The installed modules decide which resources and filters exist. The client passes filters and comparison types to the server. It does not check them. [Compatibility](compatibility.md)

## Related pages

- [Python API](usage.md): methods, verified listings, and writes.
- [Snapshot format](snapshot-format.md): what a snapshot holds.
- [Command line](cli.md) and [MCP tools](mcp.md): the same limits apply.
