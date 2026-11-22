# Playground

The playground runs the Python client in your browser. It uses Pyodide 314.0.8 in a web worker. Open it at <https://maehr.github.io/omeka-s-client/>. The playground is independent of the Omeka project.

The playground shows the client calls for each action. It prints the Python snippet, the HTTP requests, and the JSON result.

## Demo mode

Demo mode uses `FakeOmeka`. This fake server runs in memory. It holds sample items, item sets, and media.

Use demo mode to try reads, writes, and uploads. No data leaves your browser.

Use the reset button to restore the sample data. Reloading the page also restores it.

## Live mode

Live mode reads from a public Omeka S installation. It sends only GET requests. It sends no API keys.

The browser enforces CORS. The server must send these headers.

- `Access-Control-Allow-Origin`
- `Access-Control-Expose-Headers: Link, Omeka-S-Total-Results`

The playground drops request headers that are not CORS-safelisted. Examples are `Cache-Control` and `User-Agent`. This avoids a preflight request.

A list action fails if the browser hides the total header.

## Limits

- Snapshot capture is not available. `capture_snapshot` starts threads. Pyodide cannot start threads.
- File download is not available. `download` uses `os.link`. Pyodide does not supply `os.link`.
- Live mode cannot write.
- The command line and MCP server are not available.
- The playground keeps no data between page loads.
- `FakeOmeka` supports only some filters. The playground rejects the other filters.

## Run locally

Build the package and the site. Then serve the site.

```bash
uv build && sh playground/build.sh && python3 -m http.server -d _site
```

Open <http://localhost:8000/>.

Run the smoke test after you build.

```bash
npm install --no-save pyodide@314.0.8
node playground/smoke.mjs
```
