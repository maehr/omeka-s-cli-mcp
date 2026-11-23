import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs";

const status = (text, ready = false) => postMessage({ type: "status", text, ready });

const ready = (async () => {
  status("Loading Pyodide...");
  const pyodide = await loadPyodide();
  status("Installing omeka_s_client...");
  await pyodide.loadPackage("micropip");
  const res = await fetch("wheel.txt");
  const wheel = res.ok ? (await res.text()).trim() : "";
  if (!wheel.endsWith(".whl")) {
    throw new Error("wheel.txt is missing. Run uv build && sh playground/build.sh, then serve _site, not playground/.");
  }
  await pyodide.pyimport("micropip").install(new URL(wheel, self.location).href);
  const src = await (await fetch("playground.py")).text();
  pyodide.FS.mkdirTree("/home/pyodide");
  pyodide.FS.writeFile("/home/pyodide/playground.py", src);
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  const mod = pyodide.pyimport("playground");
  const send = pyodide.pyimport("pyodide.http").pyxhr.get;
  status("Ready. omeka-s-client " + wheel.split("-")[1] + ".", true);
  return { mod, demo: mod.Demo(), send };
})();
ready.catch((e) => status("Failed to start: " + e));

onmessage = async ({ data }) => {
  let ctx;
  try {
    ctx = await ready;
  } catch (e) {
    postMessage({ type: "result", data: { ok: false, error: "WorkerError", message: String(e), status: null, snippet: "", requests: [], warnings: [] } });
    return;
  }
  const { mod, demo, send } = ctx;
  if (data.type === "reset") {
    demo.reset();
    status("Demo data reset.", true);
    return;
  }
  const live = data.payload.mode === "live";
  try {
    const out = mod.run_json(JSON.stringify(data.payload), demo, live ? send : null);
    postMessage({ type: "result", data: JSON.parse(out) });
  } catch (e) {
    postMessage({ type: "result", data: { ok: false, error: "PythonError", message: String(e).split("\n").slice(-2).join(" "), status: null, snippet: "", requests: [], warnings: [] } });
  }
};
