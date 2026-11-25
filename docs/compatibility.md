# Compatibility

The integration tests pass on the versions below. The last column lists the core comparison types of each Omeka S version. The tests do not check each comparison type.

| Omeka S | Test result | Core property filter types |
| --- | --- | --- |
| 3.2.3 | Passed | `eq`, `neq`, `in`, `nin`, `res`, `nres`, `ex`, `nex` |
| 4.1.1 | Passed | The preceding types and `sw`, `nsw`, `ew`, `new` |
| 4.2.1 | Passed | The preceding types and `dt`, `ndt` |

Omeka S 4.0 adds the prefix and suffix comparison types. Omeka S 4.2 adds comparisons by data type. Modules can supply more types. The client passes the comparison type to the server. It does not implement the comparison itself. [Omeka S REST API](https://omeka.org/s/docs/developer/api/rest_api/)

The integration tests use Python 3.11 and an Omeka S installation under `/collection`. They check pagination, scope of API keys, property terms, multipart uploads, downloads, RDF replacement, and snapshot capture. The offline tests passed on Python 3.11 through 3.15 on macOS.
The CI matrix also checks these versions on Linux and Python 3.13 on Windows.

The tests do not check each resource and method combination. They do not check resources that modules add. [API coverage](api-coverage.md)

The deletion tests check that Omeka S removes the item on all three versions. Versions 3.2.3 and 4.1.1 can return HTTP 500 after they delete an item. Version 4.2.0 fixes the response error. Check the record before you repeat a deletion after a server error. [Omeka S 4.2.0 release notes](https://github.com/omeka/omeka-s/releases/tag/v4.2.0)

Omeka S 3.2.3 adds `sort_by=id` and `sort_order=asc` to next links when the request omits them. The tested 4.x versions also add empty `sort_by_default` and `sort_order_default` parameters. The client accepts those defaults and checks the remaining filters.

Use `page` and `per_page` for paging. Read `api_resources` for JSON resource discovery. Omeka S returns all API resources in one response. It ignores `page` and `per_page` and sends no total count. So `page("api_resources")` returns the complete list. A verified listing of `api_resources` fails, because the response has no count and the IDs are not numbers. The `/api` path returns an HTML page.

## Pyodide

The playground runs on Pyodide 314.0.8. The synchronous transport needs JSPI in the browser. The playground instead uses `pyodide.http.pyxhr` in a web worker. Snapshot capture is not supported because it starts threads. File download is not supported because Pyodide has no `os.link`. [Playground](playground.md)
