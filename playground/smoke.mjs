import { readFileSync } from "node:fs";
import { loadPyodide } from "pyodide";

const wheel = readFileSync("_site/wheel.txt", "utf8").trim();
const pyodide = await loadPyodide();
pyodide.FS.writeFile("/tmp/" + wheel, readFileSync("_site/" + wheel));
await pyodide.loadPackage("micropip");
await pyodide.pyimport("micropip").install("emfs:/tmp/" + wheel);
pyodide.FS.writeFile("/tmp/playground.py", readFileSync("_site/playground.py"));
pyodide.runPython("import sys; sys.path.insert(0, '/tmp')");
const mod = pyodide.pyimport("playground");
const demo = mod.Demo();

const prop = { property: "dcterms:title", type: "eq", value: "x", joiner: "and" };
const title = [{ type: "literal", property_id: 1, "@value": "Smoke" }];
const cases = [
  ["get", { resource: "items", id: 1 }, true],
  ["page", { resource: "items", page: 1, per_page: 5, filters: [["item_set_id", "1"]], conditions: [prop] }, true],
  ["list", { resource: "items", per_page: 5, verify: true, expected_ids: Array.from({ length: 12 }, (_, i) => i + 1) }, true],
  ["list", { resource: "items", conditions: [{ property: "dcterms:identifier", type: "eq", value: "letter-001", joiner: "and" }] }, true, null, [1]],
  ["list", { resource: "media", verify: true }, true],
  ["create", { resource: "items", payload: { "dcterms:title": title } }, true],
  ["patch", { resource: "items", id: 1, payload: { "dcterms:title": title }, replace_rdf_values: true }, true],
  ["delete", { resource: "items", id: 2, confirm: true }, true],
  ["upload", { payload: { "dcterms:title": title }, filename: "up.txt", text: "hi" }, true],
  ["page", { resource: "items", filters: [["search", "x"]] }, false, "does not support"],
  ["delete", { resource: "items", id: 3, confirm: false }, false],
];

let failed = 0;
for (const [op, args, ok, text, ids] of cases) {
  let out;
  try {
    out = JSON.parse(mod.run_json(JSON.stringify({ mode: "demo", op, args }), demo, null));
  } catch (e) {
    out = { ok: null, message: String(e).split("\n").slice(-2).join(" ") };
  }
  const got = ids ? JSON.stringify((out.result || []).map((r) => r["o:id"])) : null;
  const pass = out.ok === ok && (!ids || got === JSON.stringify(ids)) && (!text || String(out.message).includes(text));
  if (!pass) failed++;
  console.log((pass ? "PASS " : "FAIL ") + op + (ok ? "" : " (expect error)") + (pass ? "" : " " + JSON.stringify(out)));
}
console.log(failed ? failed + " failed" : "all passed");
process.exit(failed ? 1 : 0);
