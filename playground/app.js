"use strict";
const $ = (id) => document.getElementById(id);
const worker = new Worker("worker.js", { type: "module" });
let busy = false;

const mode = () => document.querySelector('input[name="mode"]:checked').value;
const LIVE_OPS = ["get", "page", "list"];

function refresh() {
  const live = mode() === "live";
  $("live-box").hidden = !live;
  for (const o of $("op").options) o.disabled = live && !LIVE_OPS.includes(o.value);
  if ($("op").selectedOptions[0].disabled) $("op").value = "get";
  const op = $("op").value;
  for (const el of document.querySelectorAll("[data-ops]")) {
    el.hidden = !el.dataset.ops.split(" ").includes(op);
  }
  $("reset").hidden = live;
}

function pairs() {
  return $("filters").value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.indexOf("=");
    if (i < 1) throw new Error("Filter must be key=value: " + l);
    return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  });
}

function conditions() {
  const property = $("cond-property").value.trim();
  if (!property) return [];
  return [{ property, type: $("cond-type").value.trim() || "eq", value: $("cond-value").value, joiner: "and" }];
}

function buildArgs(op) {
  const resource = $("resource").value.trim();
  const id = Number($("id").value);
  const json = () => JSON.parse($("payload").value);
  switch (op) {
    case "get": return { resource, id };
    case "page":
      return { resource, page: Number($("page").value), per_page: Number($("per_page").value), filters: pairs(), conditions: conditions() };
    case "list": {
      const ids = $("expected_ids").value.split(",").map((s) => s.trim()).filter(Boolean).map(Number);
      return { resource, per_page: Number($("per_page").value), filters: pairs(), conditions: conditions(),
        verify: $("verify").checked, expected_ids: ids.length ? ids : null };
    }
    case "create": return { resource, payload: json() };
    case "patch": return { resource, id, payload: json(), replace_rdf_values: $("replace_rdf_values").checked };
    case "delete": return { resource, id, confirm: $("confirm").checked };
    case "upload": return { payload: json(), filename: $("filename").value, text: $("text").value };
  }
}

function fill(list, items) {
  list.replaceChildren(...items.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
}

function render(r) {
  const err = $("error");
  err.hidden = r.ok;
  if (r.ok) {
    $("output").textContent = JSON.stringify(r.result, null, 2);
  } else {
    err.textContent = r.error + (r.status ? " (HTTP " + r.status + ")" : "") + ": " + r.message;
    $("output").textContent = "";
  }
  $("snippet").textContent = r.snippet || "";
  fill($("requests"), r.requests || []);
  fill($("warnings"), r.warnings || []);
}

function setBusy(b) {
  busy = b;
  $("run").disabled = b;
  $("reset").disabled = b;
}

worker.onmessage = ({ data }) => {
  if (data.type === "status") {
    $("status").textContent = data.text;
    if (data.ready) setBusy(false);
  } else if (data.type === "result") {
    render(data.data);
    $("status").textContent = "Done.";
    setBusy(false);
  }
};
worker.onerror = (e) => { $("status").textContent = "Worker error: " + e.message; };

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (busy) return;
  const op = $("op").value;
  let args;
  try {
    args = buildArgs(op);
  } catch (ex) {
    render({ ok: false, error: "InputError", message: String(ex.message || ex), status: null });
    return;
  }
  if (op === "delete" && !(args.confirm && window.confirm("Delete " + args.resource + " " + args.id + "?"))) {
    render({ ok: false, error: "NotConfirmed", message: "Tick Confirm delete and accept the prompt.", status: null });
    return;
  }
  const payload = { mode: mode(), op, args };
  if (payload.mode === "live") payload.url = $("url").value.trim();
  setBusy(true);
  $("status").textContent = "Running...";
  worker.postMessage({ type: "run", payload });
});

$("reset").addEventListener("click", () => { setBusy(true); worker.postMessage({ type: "reset" }); });
$("copy").addEventListener("click", () => navigator.clipboard.writeText($("snippet").textContent));
$("op").addEventListener("change", refresh);
for (const r of document.querySelectorAll('input[name="mode"]')) r.addEventListener("change", refresh);
refresh();
