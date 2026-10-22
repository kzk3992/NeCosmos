// NeCosmos v0.10 main: UI, ネコキウイ economy (outside the ecology), saves, observers, test API.
// The simulation runs in a Web Worker (Pyodide + the frozen Python/NumPy core); the UI never blocks on it.
import { World3D } from "./render.js";

const VERSION = "0.10.0";
const SAVE_KEY = "necosmos_v010_save", META_KEY = "necosmos_v010_meta";
const SPECIES_JP = { grass: "草ねこ", mogumogu: "もぐもぐねこ", kinoko: "きのこねこ", fuwa: "ふわふわねこ", chie: "知恵ねこ",
  tori: "鳥ねこ", sakana: "魚ねこ", slime: "スライムねこ" };
const SPECIES_COL = { grass: "#79bd79", mogumogu: "#efae77", kinoko: "#bb8adb", fuwa: "#d6e8ed", chie: "#d7b7ff",
  tori: "#f1d76f", sakana: "#77cfe0", slime: "#84dda5" };
const ACTION_JP = ["休む", "移動", "光合成", "食事", "分解", "出産", "飛行・運搬"];
const UNLOCK_COST = [0, 150, 300, 450];
const EVAL_PERIOD = 300;
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ worker client
class Engine {
  constructor() { this.seq = 0; this.pending = new Map(); this.onProgress = () => {}; this.start(); }
  start() {
    this.worker = new Worker("/js/worker.js");
    this.worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === "progress") return this.onProgress(m);
      const p = this.pending.get(m.id);
      if (!p) return;
      this.pending.delete(m.id);
      m.ok ? p.ok(m.result) : p.bad(new Error(m.error));
    };
    this.worker.onerror = (e) => { for (const p of this.pending.values()) p.bad(new Error(e.message || "worker error")); this.pending.clear(); };
  }
  // one request in flight at a time: init / step / save / load / place are strictly serialized
  call(cmd, ...args) {
    const run = () => new Promise((ok, bad) => {
      const id = ++this.seq;
      this.pending.set(id, { ok, bad });
      this.worker.postMessage({ id, cmd, args });
    });
    const p = (this.queue || Promise.resolve()).then(run, run);
    this.queue = p.catch(() => {});
    return p;
  }
  restart() { this.worker.terminate(); this.pending.clear(); this.queue = Promise.resolve(); this.start(); }
}

// ------------------------------------------------------------------ app state
const app = {
  engine: null, world: null, catalog: null, ready: false, status: "loading", error: null,
  state: null, running: false, speed: 5, busy: false, kiwi: 80, history: [], evaluations: [], log: [],
  mode: "view", placeId: null, placeYaw: 0, ghostOk: false, params: null, ending: null,
};

function setStatus(s, detail) {
  app.status = s;
  $("status").textContent = detail || s;
  $("status").className = "status " + s;
}

function log(day, text, kind = "info") {
  app.log.unshift({ day, text, kind });
  app.log = app.log.slice(0, 120);
  renderLog();
}

// ------------------------------------------------------------------ economy (external to ecology)
function kiwiIncome(st) {
  const alive = Object.values(st.counts).filter((c) => c > 0).length;
  const total = Object.values(st.counts).reduce((a, b) => a + b, 0);
  return 0.05 * alive + 0.002 * Math.min(total, 500);       // observation reward; never feeds back into matter
}

// ------------------------------------------------------------------ simulation control
async function waitIdle() { while (app.busy) await new Promise((r) => setTimeout(r, 30)); }
function readMeta() { try { const m = JSON.parse(localStorage.getItem(META_KEY) || "null"); return m && typeof m === "object" ? m : null; } catch { return null; } }

async function newWorld(params) {
  app.running = false;
  await waitIdle();
  setStatus("busy", "新しい世界をつくっています…");
  app.busy = true;
  let st;
  try { st = await app.engine.call("new", params); } finally { app.busy = false; }
  app.params = params;
  for (const k of ["terrain", "climate", "composition", "seed"]) if (params[k] != null) $(k).value = params[k];
  app.kiwi = 80; app.history = []; app.evaluations = []; app.log = []; app.ending = null;
  app.state = st;
  app.world.setWorld(st);
  log(0, `新しい世界：${terrainJP(params.terrain)}・${climateJP(params.climate)}・${compJP(params.composition)}（シード ${params.seed}）`, "milestone");
  pushHistory(st);
  refreshAll();
  setStatus("ready", "準備完了 — ▶ で観察を始めましょう");
  return st;
}

async function step(n) {
  if (app.busy) throw new Error("busy");
  app.busy = true;
  try {
    const before = app.state.day;
    const st = await app.engine.call("step", n);
    applyStep(st, before);
    return st;
  } finally { app.busy = false; }
}

function applyStep(st, before) {
  app.state = st;
  app.world.update(st);
  for (const d of st.daily) {
    app.kiwi += kiwiIncome({ counts: Object.fromEntries(st.species.map((s) => [s, d[s]])) });
    if (d.day % 5 === 0) app.history.push({ day: d.day, ...Object.fromEntries(st.species.map((s) => [s, d[s]])) });
    if (d.day % EVAL_PERIOD === 0) evaluation(d.day, d);            // observer only; never changes the world
  }
  app.history = app.history.slice(-1200);
  for (const e of st.events) {
    if (e.kind === "wisdom") log(e.day, wisdomText(e.detail), "wisdom");
    else if (e.detail.startsWith("extinct:")) log(e.day, `${SPECIES_JP[e.detail.split(":")[1]] || e.detail}がいなくなった。`, "turn");
  }
  const total = Object.values(st.counts).reduce((a, b) => a + b, 0);
  if (total === 0 && !app.ending) {
    app.ending = { day: st.day, kind: "extinct" };
    log(st.day, "最後の猫が姿を消した。世界の記録として残ります（観察は続けられます）。", "milestone");
    app.running = false;
  }
  refreshAll();
}

function evaluation(day, d) {
  const st = app.state;
  const alive = st.species.filter((s) => d[s] > 0);
  const ev = { day, alive: alive.length, total: d.pop, rivers: st.river.reduce((a, b) => a + b, 0),
    ponds: st.pond.reduce((a, b) => a + b, 0), level: st.level };
  app.evaluations.push(ev);
  log(day, `【${day}日目の観察記録】${alive.length}種・${d.pop}匹。川 ${ev.rivers} 区画、池 ${ev.ponds} 区画。`, "eval");
}

function wisdomText(k) {
  return { spawn: "知恵ねこが生態系の物質から生まれた。", catnip: "知恵ねこがマタタビを置いた（60日間、繁殖しやすくなる）。",
    water: "知恵ねこが乾いた土地に水を巡らせた。", fire: "知恵ねこが焚き火を灯した。", observe: "知恵ねこは静かに見守っている。" }[k] || `知恵ねこ：${k}`;
}

function loop() {
  let last = performance.now(), acc = 0;
  setInterval(async () => {
    const now = performance.now();
    if (app.running && app.ready && !app.busy) {
      acc += ((now - last) / 1000) * app.speed;
      // Return the exact day-300 state to observers, even at high observation speed.
      const n = Math.min(Math.floor(acc), 30, EVAL_PERIOD - app.state.day % EVAL_PERIOD);
      if (n >= 1) {
        acc -= n;
        try { await step(n); } catch (e) { if (e.message !== "busy") fail(e); }
      }
    } else acc = 0;
    last = now;
  }, 100);
}

// ------------------------------------------------------------------ unlock / objects
async function buyUnlock() {
  const next = app.state.level + 1;
  if (next > 4) return;
  const cost = UNLOCK_COST[next - 1];
  if (app.kiwi < cost) return toast(`ネコキウイが足りません（${cost} 必要）`);
  const r = await app.engine.call("unlock", next);
  if (!r.ok) return toast(r.reason);
  app.kiwi -= cost;
  app.state = await app.engine.call("state");
  app.world.update(app.state);
  log(app.state.day, `生息域を拡張した（${next * 25}%）。`, "milestone");
  refreshAll();
}

function objMeta(id) { return app.catalog.objects.find((o) => o.id === id); }

function startPlace(id) {
  app.mode = "place"; app.placeId = id; app.placeYaw = 0;
  $("modeHint").textContent = `設置モード：${objMeta(id).name || id}。地面をタップで設置、R / 回転ボタンで向き、Esc で終了。カメラはドラッグで回せます。`;
  refreshShop();
}

function stopModes() {
  app.mode = "view"; app.placeId = null;
  app.world.setGhost(null);
  $("modeHint").textContent = "";
  refreshShop();
}

let lastCheck = 0;
async function previewPlace(ev) {
  const p = app.world.pickGround(ev);
  if (!p) return;
  const now = performance.now();
  app.world.setGhost(app.placeId, p.x, p.y, app.placeYaw, app.ghostOk);
  if (now - lastCheck < 120 || app.busy) return;
  lastCheck = now;
  const r = await app.engine.call("check", objMeta(app.placeId).metadata, p.x, p.y, app.placeYaw);
  app.ghostOk = r.ok;
  $("modeHint").dataset.reason = r.ok ? "" : r.reason;
  $("placeReason").textContent = r.ok ? "ここに置けます" : r.reason;
}

async function placeAt(ev) {
  const p = app.world.pickGround(ev);
  if (!p) return;
  const o = objMeta(app.placeId);
  if (app.kiwi < o.price) return toast(`ネコキウイが足りません（${o.price} 必要）`);
  while (app.busy) await new Promise((r) => setTimeout(r, 30));
  const r = await app.engine.call("place", o.metadata, p.x, p.y, app.placeYaw);
  if (!r.ok) return toast(r.reason);
  app.kiwi -= o.price;
  app.state = await app.engine.call("state");
  app.world.update(app.state);
  log(app.state.day, `${o.name || o.id}を置いた。`, "choice");
  refreshAll();
}

async function removeAt(ev) {
  const o = app.world.pickObject(ev);
  if (!o) return;
  while (app.busy) await new Promise((r) => setTimeout(r, 30));
  const r = await app.engine.call("remove", o.pid);
  if (!r.ok) return toast(r.reason);
  const meta = objMeta(o.id);
  app.kiwi += Math.floor((meta.price || 0) / 2);
  app.state = await app.engine.call("state");
  app.world.update(app.state);
  log(app.state.day, `${meta.name || o.id}を片付けた（保護も解除）。`, "choice");
  refreshAll();
}

// ------------------------------------------------------------------ save / load
async function saveGame() {
  while (app.busy) await new Promise((r) => setTimeout(r, 30));
  const blob = await app.engine.call("save");
  try {
    localStorage.setItem(SAVE_KEY, blob);
    localStorage.setItem(META_KEY, JSON.stringify({ version: VERSION, kiwi: app.kiwi, history: app.history.slice(-600),
      evaluations: app.evaluations, log: app.log.slice(0, 60), params: app.params, ending: app.ending, savedAt: Date.now() }));
    toast(`保存しました（${app.state.day}日目）`);
    return true;
  } catch (e) { toast("保存に失敗しました：" + e.message); return false; }
}

async function loadGame() {
  const blob = localStorage.getItem(SAVE_KEY), meta = readMeta();
  if (!blob || !meta || meta.version !== VERSION) { toast("v0.10 の保存データがありません"); return false; }
  app.running = false;
  await waitIdle();
  app.busy = true;
  let st;
  try { st = await app.engine.call("load", blob); }
  catch (e) { toast("保存データを読み込めませんでした（壊れている可能性があります）"); console.warn("[load]", e); return false; }
  finally { app.busy = false; }
  const arr = (v) => (Array.isArray(v) ? v : []);
  Object.assign(app, { kiwi: Number.isFinite(meta.kiwi) ? meta.kiwi : 0, history: arr(meta.history), evaluations: arr(meta.evaluations),
    log: arr(meta.log), params: meta.params && typeof meta.params === "object" ? meta.params : app.params, ending: meta.ending ?? null, state: st });
  app.world.setWorld(st);
  refreshAll();
  toast(`読み込みました（${st.day}日目）`);
  return true;
}

// ------------------------------------------------------------------ UI rendering
const terrainJP = (t) => ({ flat: "平原", hills: "丘陵", valley: "谷", depression: "窪地", initial_river: "川のある平原", mountain: "中央に山" })[t] || t;
const climateJP = (c) => ({ tundra: "苔原", wet: "湿潤", dry: "乾燥", cold: "寒冷", moss: "温暖（旧）" })[c] || c;
const compJP = (c) => ({ producers: "草ねこだけ", pcd: "草・もぐもぐ・きのこ", all8: "8種すべて" })[c] || c;

function pushHistory(st) { app.history.push({ day: st.day, ...st.counts }); }

function refreshAll() {
  const st = app.state;
  if (!st) return;
  $("day").textContent = `${st.day}日目`;
  $("kiwi").textContent = Math.floor(app.kiwi);
  const total = Object.values(st.counts).reduce((a, b) => a + b, 0);
  $("total").textContent = `${total} / ${st.maxPopulation || 200}匹`;
  $("species").innerHTML = st.species.map((s) =>
    `<div class="sp ${st.counts[s] ? "" : "gone"}"><i style="background:${SPECIES_COL[s]}"></i>${SPECIES_JP[s]}<b>${st.counts[s]}</b></div>`).join("");
  const next = st.level + 1;
  $("unlockBtn").textContent = next <= 4 ? `生息域を ${next * 25}% に広げる（${UNLOCK_COST[next - 1]} キウイ）` : "生息域は最大です";
  $("unlockBtn").disabled = next > 4 || app.kiwi < (UNLOCK_COST[next - 1] || 0);
  $("level").textContent = `生息域 ${st.level * 25}%`;
  $("playBtn").textContent = app.running ? "⏸ 一時停止" : "▶ 観察";
  const subs = st.objects.filter((o) => o.submerged);
  $("objects").innerHTML = st.objects.length ? st.objects.map((o) =>
    `<div class="obj">${objMeta(o.id)?.name || o.id}${o.submerged ? ' <span class="wet">水没中</span>' : ""}</div>`).join("") : '<div class="muted">まだ何も置いていません</div>';
  $("waterInfo").textContent = `川 ${st.river.reduce((a, b) => a + b, 0)} 区画・池 ${st.pond.reduce((a, b) => a + b, 0)} 区画${subs.length ? `・水没 ${subs.length}` : ""}`;
  refreshShop();
  drawChart();
}

function refreshShop() {
  if (!app.catalog) return;
  const groups = { furniture: "猫の家具", nature: "自然の飾り", environment: "環境オブジェクト" };
  $("shop").innerHTML = Object.entries(groups).map(([cat, title]) => `<h4>${title}</h4><div class="grid">` +
    app.catalog.objects.filter((o) => (o.metadata.category || "nature") === cat).map((o) =>
      `<button class="item ${app.placeId === o.id ? "on" : ""}" data-id="${o.id}" ${app.kiwi < o.price ? "disabled" : ""}>${o.name || o.id}<small>${o.price} 🥝</small></button>`).join("") + "</div>").join("");
  for (const b of document.querySelectorAll("#shop .item")) b.onclick = () => startPlace(b.dataset.id);
  $("removeBtn").classList.toggle("on", app.mode === "remove");
}

function renderLog() {
  $("log").innerHTML = app.log.slice(0, 40).map((e) => `<div class="ev ${e.kind}"><span>${e.day}日</span>${e.text}</div>`).join("");
}

function drawChart() {
  const c = $("chart"), g = c.getContext("2d");
  const w = c.width = c.clientWidth * devicePixelRatio, h = c.height = c.clientHeight * devicePixelRatio;
  g.clearRect(0, 0, w, h);
  const H = app.history;
  if (H.length < 2) return;
  const max = Math.max(5, ...H.map((r) => Math.max(...app.state.species.map((s) => r[s] || 0))));
  const d0 = H[0].day, d1 = H[H.length - 1].day || 1;
  for (const s of app.state.species) {
    g.strokeStyle = SPECIES_COL[s]; g.lineWidth = 1.5 * devicePixelRatio; g.beginPath();
    H.forEach((r, k) => { const x = ((r.day - d0) / Math.max(d1 - d0, 1)) * w, y = h - ((r[s] || 0) / max) * (h - 4) - 2; k ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  }
}

let toastTimer;
function toast(t) { $("toast").textContent = t; $("toast").classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").classList.remove("show"), 2600); }

function fail(e) {
  console.error(e);
  app.error = String(e.message || e);
  app.running = false;
  setStatus("error", "エラー：" + app.error);
  $("retry").hidden = false;
}

// ------------------------------------------------------------------ wiring
function wire() {
  $("newBtn").onclick = async () => {
    const seed = Number($("seed").value);
    if (!Number.isInteger(seed) || seed < 0 || seed > 4294967295) return toast("シードは0〜4294967295の整数にしてください");
    try { await newWorld({ terrain: $("terrain").value, climate: $("climate").value,
      composition: $("composition").value, seed }); } catch (e) { fail(e); }
  };
  $("randSeed").onclick = () => { $("seed").value = Math.floor(Math.random() * 1e6); };
  $("playBtn").onclick = () => { app.running = !app.running; refreshAll(); };
  for (const b of document.querySelectorAll("[data-speed]")) b.onclick = () => {
    app.speed = +b.dataset.speed;
    document.querySelectorAll("[data-speed]").forEach((x) => x.classList.toggle("on", x === b));
  };
  $("unlockBtn").onclick = buyUnlock;
  $("saveBtn").onclick = saveGame;
  $("loadBtn").onclick = loadGame;
  $("removeBtn").onclick = () => { app.mode = app.mode === "remove" ? "view" : "remove"; app.world.setGhost(null); app.placeId = null;
    $("modeHint").textContent = app.mode === "remove" ? "片付けモード：置いたものをタップすると片付けます（代金の半分が戻ります）。" : ""; refreshShop(); };
  $("rotateBtn").onclick = () => { app.placeYaw = (app.placeYaw + 45) % 360; };
  $("catScale").oninput = (e) => { app.world.catScale = +e.target.value; if (app.state) app.world.updateCats(app.state); };
  $("aboutBtn").onclick = () => $("about").showModal();
  $("retry").onclick = () => { $("retry").hidden = true; app.engine.restart(); boot(); };
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") stopModes(); if ((e.key === "r" || e.key === "R") && app.mode === "place") app.placeYaw = (app.placeYaw + 45) % 360; });
  const canvas = app.world.renderer.domElement;
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointermove", (e) => { if (app.mode === "place") previewPlace(e); });
  canvas.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;     // a drag moves the camera
    if (app.mode === "place") placeAt(e);
    else if (app.mode === "remove") removeAt(e);
    else {
      const c = app.world.pickCat(e);
      $("catInfo").innerHTML = c ? `<b>${SPECIES_JP[c.sp]}</b> #${c.id}<br>年齢 ${c.age} 歳（1日=1年）・エネルギー ${c.energy.toFixed(2)}・体重 ${c.mass.toFixed(3)} kg<br>いまの行動：${ACTION_JP[c.action] || "—"}` : "";
    }
  });
}

async function boot() {
  try {
    setStatus("loading", "シミュレーションエンジンを読み込み中…");
    app.engine.onProgress = (m) => setStatus("loading", m.detail);
    const info = await app.engine.call("init");
    app.engineInfo = info;
    app.ready = true;
    const saved = localStorage.getItem(SAVE_KEY);
    const meta = readMeta();
    if (!(saved && meta && meta.version === VERSION && await loadGame())) await newWorld({ terrain: $("terrain").value, climate: $("climate").value, composition: $("composition").value, seed: parseInt($("seed").value, 10) });
    readyResolve(true);
  } catch (e) { fail(e); }
}

let readyResolve;
const readyPromise = new Promise((r) => { readyResolve = r; });

// ------------------------------------------------------------------ test API (browser checks)
window.NeCosmos = {
  version: VERSION,
  ready: readyPromise,
  get status() { return { status: app.status, error: app.error, ready: app.ready, day: app.state?.day, engine: app.engineInfo }; },
  newWorld: (p) => newWorld(p),
  async step(n) { app.running = false; while (app.busy) await new Promise((r) => setTimeout(r, 20)); let st; let left = n; while (left > 0) { const k = Math.min(left, 50, EVAL_PERIOD - app.state.day % EVAL_PERIOD); st = await step(k); left -= k; } return st; },
  state: () => app.state,
  residual: () => app.state?.residual,
  hash: () => app.engine.call("hash"),
  save: saveGame, load: loadGame,
  check: (id, x, y, yaw = 0) => app.engine.call("check", objMeta(id).metadata, x, y, yaw),
  async place(id, x, y, yaw = 0) { const r = await app.engine.call("place", objMeta(id).metadata, x, y, yaw); if (r.ok) { app.state = await app.engine.call("state"); app.world.update(app.state); refreshAll(); } return r; },
  async remove(pid) { const r = await app.engine.call("remove", pid); if (r.ok) { app.state = await app.engine.call("state"); app.world.update(app.state); refreshAll(); } return r; },
  async unlock(level) { const r = await app.engine.call("unlock", level); if (r.ok) { app.state = await app.engine.call("state"); app.world.update(app.state); refreshAll(); } return r; },
  get kiwi() { return app.kiwi; },
  evaluations: () => app.evaluations,
};

(async function main() {
  try {
    app.catalog = await (await fetch("/assets/catalog.json")).json();
    app.world = new World3D($("view"), app.catalog);
    app.engine = new Engine();
    wire();
    loop();
    await boot();
    if (new URLSearchParams(location.search).get("smoke") === "1") (await import("./smoke.js")).runSmoke();
  } catch (e) { fail(e); }
})();
