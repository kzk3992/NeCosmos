/* NeCosmos v0.10 simulation worker: runs the frozen Python+NumPy core in Pyodide (self-hosted).
   Messages in:  {id, cmd, args}   cmds: init, new, step, state, unlock, check, place, remove, save, load, hash
   Messages out: {id, ok, result | error}, plus {type:'progress', stage, detail} during init. */
"use strict";
let py = null;
let bridge = null;

function progress(stage, detail) { postMessage({ type: "progress", stage, detail }); }

async function fetchText(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return await r.text();
}

async function init() {
  progress("runtime", "Pyodide を読み込み中");
  importScripts("/vendor/pyodide/pyodide.js");
  py = await loadPyodide({ indexURL: "/vendor/pyodide/" });
  progress("numpy", "NumPy を読み込み中");
  await py.loadPackage("numpy");
  progress("engine", "シミュレーションのファイルを展開中");
  const manifest = JSON.parse(await fetchText("/engine/manifest.json"));
  const files = manifest.files || [];
  for (let k = 0; k < files.length; k++) {
    const rel = files[k];
    const text = await fetchText("/engine/" + rel);
    const path = "/workspace/" + rel;
    const dir = path.slice(0, path.lastIndexOf("/"));
    py.FS.mkdirTree(dir);
    py.FS.writeFile(path, text);
    if (k % 5 === 0) progress("engine", `ファイル ${k + 1}/${files.length}`);
  }
  py.FS.mkdirTree("/workspace/bridge");
  py.FS.writeFile("/workspace/bridge/bridge.py", await fetchText("/engine/bridge.py"));
  await py.runPythonAsync(`
import sys
sys.path.insert(0, "/workspace/NeCosmos-Simulation")
sys.path.insert(0, "/workspace/bridge")
import bridge
`);
  bridge = py.globals.get("bridge");
  progress("ready", "準備完了");
  return { files: files.length, pyodide: py.version };
}

function call(fn, ...args) {
  const out = bridge[fn](...args);
  return typeof out === "string" ? out : String(out);
}

const handlers = {
  init: async () => init(),
  new: async (p) => JSON.parse(call("new_world", JSON.stringify(p))),
  step: async (n) => {
    const start=performance.now();
    const result=JSON.parse(call("step",n));
    result.performance={stepMs:performance.now()-start,days:n};return result;
  },
  observe: async fraction => JSON.parse(call("observe", fraction)),
  prepare: async () => JSON.parse(call("prepare")),
  state: async () => JSON.parse(call("state")),
  unlock: async (lvl) => JSON.parse(call("unlock", lvl)),
  check: async (meta, x, y, yaw) => JSON.parse(call("check_place", JSON.stringify(meta), x, y, yaw)),
  place: async (meta, x, y, yaw) => JSON.parse(call("place", JSON.stringify(meta), x, y, yaw)),
  remove: async (pid) => JSON.parse(call("remove", pid)),
  save: async () => call("save"),
  load: async (b64) => JSON.parse(call("load", b64)),
  hash: async () => call("state_hash"),
  memory: async () => ({wasmLinearMemoryBytes:py._module.HEAPU8.buffer.byteLength}),
};

onmessage = async (ev) => {
  const { id, cmd, args } = ev.data;
  try {
    if (cmd !== "init" && !bridge) throw new Error("engine not ready");
    const result = await handlers[cmd](...(args || []));
    postMessage({ id, ok: true, result });
  } catch (e) {
    postMessage({ id, ok: false, error: String(e && e.message ? e.message : e) });
  }
};
