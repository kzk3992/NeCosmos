"""NeCosmos v0.10 browser bridge (runs inside Pyodide, in a Web Worker).

Thin wrapper over the verified Phase 4 core (/workspace/NeCosmos-Simulation):
  * new_world / step / state      -> the real Simulation, day by day
  * unlock(level)                  -> player-bought habitat expansion (fixed footprint; 25/50/75/100 %)
  * check_place / place / remove   -> placeable objects; TerrainProtected objects use the core's own
                                      protection API (protection.place / protection_field). Bridge
                                      footings (metadata footprint.parts) are protected per part.
  * save / load / state_hash       -> safe tagged-JSON codec (allowlisted classes, zlib, base64); no pickle
Nothing here changes equations, parameters or matter: placing an object only moves soil inside its
footprint (volume neutral, as in the core) and recomputes the protection field.
"""
import copy
import base64
import hashlib
import json
import math
import zlib

import numpy as np

# ---- wasm32 ABI shim (Pyodide: np.intp is 32-bit; the frozen core uses explicit int64 index arrays).
# np.bincount refuses the int64 -> int32 cast. We adapt INDEX arrays only: integer dtype required, every
# value checked to fit np.intp (else raise), exact cast, then the original call with weights/minlength
# unchanged. No clipping, no float casts, no numeric change. Native 64-bit NumPy is left untouched.
WASM_INDEX_SHIM = np.dtype(np.intp).itemsize < 8
if WASM_INDEX_SHIM:
    _orig_bincount = np.bincount
    _lo, _hi = np.iinfo(np.intp).min, np.iinfo(np.intp).max

    def _bincount_intp(x, weights=None, minlength=0):
        a = np.asarray(x)
        if a.dtype.kind not in "iu":
            raise TypeError(f"bincount index dtype {a.dtype} is not integer")
        if a.size and (int(a.min()) < _lo or int(a.max()) > _hi):
            raise OverflowError("bincount index outside np.intp range")
        return _orig_bincount(a.astype(np.intp, copy=False), weights=weights, minlength=minlength)
    np.bincount = _bincount_intp

from src.coupling.simulation import SP, Simulation, load_cfg
from src.terrain import generate, protection
from src.weather.generator import WeatherGenerator, Weather
from dataclasses import asdict

FROZEN = "/workspace/NeCosmos-Simulation/configs/scenarios/frozen.json"
STATE = {"sim": None, "objects": {}, "next_pid": 1, "params": None}
MAX_POPULATION = 200


def _frozen_overrides():
    with open(FROZEN, encoding="utf-8") as f:
        return json.load(f)["overrides"]


# Phase 3 "central_mountain" preset as an initial condition only, expressed with the core's existing
# noise/hill ops. Phase 3 metres (centre origin) -> cells: i = (x + 8)/0.5 - 0.5, radius_cells = r/0.5.
# Core noise uses base_res 4 (Phase 3 used 3), an approximation. Phase 3's relax(maxDeg 45, 40 iterations)
# has no core op, so it is applied once to the generated bedrock below, before the Simulation computes its
# initial storages; daily physics is untouched. This preset is NOT part of the Phase 4 360-run matrix.
MOUNTAIN = {"desc": "v0.10 game preset from Phase 3 central_mountain (not in the 360-run matrix)",
            "ops": [["noise", 0.08, 2], ["hill", 15.5, 15.5, 7.2, 2.1], ["hill", 16.9, 16.3, 2.4, 0.35]],
            "relax_max_slope": 1.0, "relax_iterations": 40}
_core_build = generate.build


def _relax(z, dx, max_slope, iterations):
    """Pairwise neighbour relaxation toward |dz| <= max_slope*dx; volume-conserving, rim fixed."""
    z = z.copy()
    lim = max_slope * dx
    for _ in range(iterations):
        for ax in (0, 1):
            d = np.diff(z, axis=ax)
            m = np.sign(d) * np.maximum(np.abs(d) - lim, 0) * 0.25
            if ax == 0:
                z[:-1] += m; z[1:] -= m
            else:
                z[:, :-1] += m; z[:, 1:] -= m
    return z


def _build_with_relax(terrain_cfg, name, seed):
    ter = _core_build(terrain_cfg, name, seed)
    t = terrain_cfg["terrains"][name]
    if "relax_max_slope" in t:
        b = _relax(ter["bedrock"], ter["dx"], t["relax_max_slope"], t["relax_iterations"])
        ter["bedrock"] = np.where(ter["rim"], ter["bedrock"], b)
    return ter


generate.build = _build_with_relax


def new_world(params_json):
    p = json.loads(params_json)
    if not isinstance(p.get("seed"), int) or not 0 <= p["seed"] <= 0xFFFFFFFF:
        raise ValueError("シードは0〜4294967295の整数にしてください")
    mode = p.get('weatherMode', 'normal')
    if mode not in ('fixed', 'normal', 'wet', 'dry', 'extreme'):
        raise ValueError('天候の設定が不正です')
    p['weatherMode'] = mode
    ov = _frozen_overrides()
    if p["terrain"] == "mountain":
        ov["terrain.terrains.mountain"] = MOUNTAIN
    sc = {"terrain": p["terrain"], "climate": p["climate"], "composition": p["composition"],
          "seed": int(p["seed"]), "days": 10 ** 9, "unlock": "fixed", "overrides": ov, "weather_mode": mode, "max_population": MAX_POPULATION}
    STATE.pop("pending_sim", None)
    STATE.pop("pending_row", None)
    STATE["sim"] = Simulation(sc)
    STATE["sim"].eco.max_population = MAX_POPULATION
    STATE["objects"] = {}
    STATE["next_pid"] = 1
    STATE["params"] = p
    STATE["behavior_events"] = []
    return state(include_static=True)


def step(n):
    sim = STATE["sim"]
    if not isinstance(n, (int, float)) or int(n) != n or not 1 <= n <= 300:
        raise ValueError("step requires 1..300 whole planet days")
    rows = []
    behavior_events = []
    for _ in range(int(n)):
        p = sim.eco.pop
        before = {int(cid): (int(p.j[k]), int(p.i[k])) for k, cid in enumerate(p.id)}
        deaths_start = len(sim.eco.deaths)
        pending = STATE.pop('pending_sim', None)
        if pending is not None and pending.day == sim.day + 1:
            sim = pending
            STATE['sim'] = sim
            rows.append(STATE.pop('pending_row'))
        else:
            rows.append(sim.step())
        p = sim.eco.pop
        for k, cid in enumerate(p.id):
            cid = int(cid)
            pos = (int(p.j[k]), int(p.i[k]))
            kinds = []
            if cid not in before: kinds.append("birth")
            else:
                if before[cid] != pos: kinds.append("move")
                if int(p.action[k]) in (3, 4): kinds.append("eat")
                elif int(p.action[k]) == 0: kinds.append("rest")
                elif int(p.action[k]) == 5: kinds.append("interact")
            for kind in kinds:
                event = dict(kind=kind, id=cid, planetTime=sim.day, position=list(pos), origin=list(before.get(cid,pos)))
                if kind == 'move':
                    event['planetTime'] = sim.day-1
                    event['endPlanetTime'] = sim.day-1 + math.hypot(pos[0]-before[cid][0],pos[1]-before[cid][1])*sim.w['dx']/75
                behavior_events.append(event)
        fed = {e['id'] for e in behavior_events if e['kind']=='eat' and e['planetTime']==sim.day}
        for e in getattr(sim.eco, 'feeding_plan', []):
            if e['id'] not in fed:
                behavior_events.append(dict(kind='eat',id=e['id'],planetTime=sim.day,position=e['position']))
        for d in sim.eco.deaths[deaths_start:]:
            behavior_events.append(dict(kind="death", id=d['id'], planetTime=sim.day, position=[d['j'],d['i']]))
        behavior_events.append(dict(kind="environmentChange", id=None, planetTime=sim.day))
    # Retained in the save for offline/headless callers; UI can aggregate these.
    STATE['behavior_events'] = behavior_events
    last = rows[-1]
    events = []
    for r in rows:
        if r["wisdom_event"]:
            events.append({"day": r["day"], "kind": "wisdom", "detail": r["wisdom_event"]})
    for d, ev in sim.tipping:
        if rows[0]["day"] <= d <= last["day"]:
            events.append({"day": d, "kind": "tipping", "detail": ev})
    out = json.loads(state())
    out["events"] = events
    out["behaviorEvents"] = behavior_events
    out["daily"] = [{"day": r["day"], "pop": r["pop_total"], **{s: r[f"pop_{s}"] for s in SP}} for r in rows]
    out["residual"] = {"water_m3": max(abs(r["res_water_m3"]) for r in rows), "soil_m3": max(abs(r["res_soil_m3"]) for r in rows),
                       "matter_kg": max(abs(r["res_matter_kg"]) for r in rows)}
    out["row"] = {k: (v if isinstance(v, (int, float, str)) else None) for k, v in last.items()}
    return json.dumps(out)


def prepare():
    """Calculate exactly once, commit only on step; no animation-dependent RNG.

    The pending daily transaction is invalidated on player world mutations and
    deliberately not auto-advanced while offline. Saves rebuild it deterministically.
    """
    if STATE.get('pending_sim') is None:
        future = copy.deepcopy(STATE['sim'])
        row = future.step()
        STATE['pending_sim'], STATE['pending_row'] = future, row
    future = STATE['pending_sim']
    return json.dumps({'day': future.day, 'moves': getattr(future.eco, 'motion_plan', []),
                       'feeds': getattr(future.eco, 'feeding_plan', []), 'cell_m': future.w['dx']})


def observe(fraction):
    """Sample engine-owned continuous positions; never run a biological step."""
    from src.ecosystem.timeline import sample
    future=STATE.get('pending_sim')
    if future is None: raise ValueError('prepare a daily transaction first')
    fraction=float(fraction)
    return json.dumps({'planetTime': STATE['sim'].day+fraction,
                       'positions': sample(getattr(future.eco,'motion_plan',[]), future.w['dx'], fraction)})


def _r(a, nd=4):
    return np.round(np.asarray(a, dtype=float), nd).ravel().tolist()


def state(include_static=False):
    sim = STATE["sim"]
    w = sim.w
    p = sim.eco.pop
    z = w["bedrock"] + w["soil"]
    out = {"day": sim.day, "level": sim.level, "maxPopulation": MAX_POPULATION, "n": int(z.shape[0]), "cell_m": w["dx"],
           "z": _r(z), "h": _r(w["h"]), "snow": _r(w["snow"]), "biome": w["biome_id"].ravel().astype(int).tolist(),
           "unlocked": w["unlocked"].ravel().astype(int).tolist(), "protection": _r(w["protection"], 3),
           "river": getattr(sim, "river_mask", getattr(sim.river, "preexisting", np.zeros_like(z, bool))).ravel().astype(int).tolist(),
           "pond": getattr(sim, "pond_mask", np.zeros_like(z, bool)).ravel().astype(int).tolist(),
           "cats": {"id": p.id.tolist(), "sp": p.sp.tolist(), "j": p.j.tolist(), "i": p.i.tolist(), "age": p.age.tolist(),
                    "energy": np.round(p.energy, 3).tolist(), "mass": np.round(p.mass, 4).tolist(), "action": p.action.tolist(),
                    "biologicalAgeYears": (p.age / 48).tolist(),
                    "behavior": [getattr(sim.eco, 'behavior', {}).get(int(cid), {}).get('state', 'idle') for cid in p.id]},
           "planetTime": sim.day, "biologicalYearDays": 48,
           "behaviorEvents": STATE.get('behavior_events', []),
           "counts": {s: int((p.sp == k).sum()) for k, s in enumerate(SP)},
           "extinct": dict(sim.extinct), "river_events": {k: v for k, v in sim.river.events.items()},
           "objects": _objects_state(), "species": SP,
           "weather": {"mode": sim.weather_driver.mode, **asdict(sim.weather_driver.current),
                       "migratedAt": getattr(sim, 'weather_migrated_at', None)}}
    if include_static:
        out["rim"] = w["rim"].ravel().astype(int).tolist()
        out["unlock_masks"] = [m.ravel().astype(int).tolist() for m in sim.unlock_masks]
    return json.dumps(out)


# ------------------------------------------------------------------ habitat expansion
def unlock(level):
    sim = STATE["sim"]
    level = int(level)
    if not (1 <= level <= len(sim.unlock_masks)) or level <= sim.level:
        return json.dumps({"ok": False, "reason": "invalid level"})
    STATE.pop("pending_sim", None)
    sim.level = level
    sim.w["unlocked"] = sim.unlock_masks[level - 1].copy()
    sim.events.append((sim.day, f"unlock level {level} (player)"))
    return json.dumps({"ok": True, "level": level})


# ------------------------------------------------------------------ objects
def _parts(meta, x, y, yaw):
    """Protected rectangles in world space: footprint.parts (e.g. bridge footings) or the whole footprint."""
    fp = meta["footprint"]
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    if fp.get("parts"):
        out = []
        for part in fp["parts"]:
            m = dict(meta, footprint={"width": part["width"], "depth": part["depth"]})
            out.append({"x": x + part["x"] * c - part["y"] * s, "y": y + part["x"] * s + part["y"] * c, "yaw": yaw, "meta": m})
        return out
    return [{"x": x, "y": y, "yaw": yaw, "meta": meta}]


def _core_cells(meta, x, y, yaw):
    w = STATE["sim"].w
    mask = np.zeros_like(w["h"], bool)
    for pt in _parts(meta, x, y, yaw):
        mask |= protection.footprint_distance(w["x"], w["y"], pt, w["dx"]) <= 0
    return mask


def _sample_z(x, y):
    w = STATE["sim"].w
    z = w["bedrock"] + w["soil"]
    n = z.shape[0]
    gi, gj = x / w["dx"] - 0.5, y / w["dx"] - 0.5
    i0, j0 = int(np.clip(math.floor(gi), 0, n - 2)), int(np.clip(math.floor(gj), 0, n - 2))
    fi, fj = min(max(gi - i0, 0), 1), min(max(gj - j0, 0), 1)
    return float((1 - fi) * (1 - fj) * z[j0, i0] + fi * (1 - fj) * z[j0, i0 + 1] + (1 - fi) * fj * z[j0 + 1, i0] + fi * fj * z[j0 + 1, i0 + 1])


def check_place(meta_json, x, y, yaw):
    meta = json.loads(meta_json)
    return json.dumps(_check(meta, float(x), float(y), float(yaw)))


def _check(meta, x, y, yaw):
    w = STATE["sim"].w
    if not (0.5 <= x <= 15.5 and 0.5 <= y <= 15.5):
        return {"ok": False, "reason": "惑星の外です"}
    core = _core_cells(meta, x, y, yaw)
    if not core.any():
        return {"ok": False, "reason": "設置範囲が小さすぎます"}
    if not w["unlocked"][core].all() or w["rim"][core].any():
        return {"ok": False, "reason": "未開放の領域です"}
    if float(w["h"][core].max()) > 0.03:        # core = footings only for bridges: water between them is fine
        return {"ok": False, "reason": "水の上には置けません" if not meta["footprint"].get("parts") else "橋台は乾いた地面に置いてください"}
    z = (w["bedrock"] + w["soil"])[core]
    lim = 0.25 if meta["terrainMode"] == "TerrainProtected" else 0.4
    if float(z.max() - z.min()) > lim:
        return {"ok": False, "reason": "傾斜が急すぎます"}
    for o in STATE["objects"].values():
        if (_core_cells(o["meta"], o["x"], o["y"], o["yaw"]) & core).any():
            return {"ok": False, "reason": "ほかの設置物と重なっています"}
    return {"ok": True}


def place(meta_json, x, y, yaw):
    meta = json.loads(meta_json)
    x, y, yaw = float(x), float(y), float(yaw)
    chk = _check(meta, x, y, yaw)
    if not chk["ok"]:
        return json.dumps(chk)
    STATE.pop("pending_sim", None)
    sim = STATE["sim"]
    pid = STATE["next_pid"]
    STATE["next_pid"] += 1
    rec = {"pid": pid, "id": meta["id"], "x": x, "y": y, "yaw": yaw, "meta": meta, "towers": []}
    if meta["terrainMode"] == "TerrainProtected" and meta["protection"]["strength"] > 0:
        for pt in _parts(meta, x, y, yaw):                       # core API: volume-neutral flatten
            tw = protection.place(sim.w, pt)
            tw["pid"] = pid
            sim.towers.append(tw)
            rec["towers"].append(len(sim.towers) - 1)
        _refresh_protection()
    STATE["objects"][pid] = rec
    return json.dumps({"ok": True, "pid": pid})


def remove(pid):
    pid = int(pid)
    rec = STATE["objects"].pop(pid, None)
    if rec is None:
        return json.dumps({"ok": False, "reason": "not found"})
    STATE.pop("pending_sim", None)
    sim = STATE["sim"]
    sim.towers = [t for t in sim.towers if t.get("pid") != pid]   # protection released
    _refresh_protection()
    return json.dumps({"ok": True})


def _refresh_protection():
    sim = STATE["sim"]
    w = sim.w
    w["protection"] = protection.protection_field(w["x"], w["y"], sim.towers, w["dx"]) if sim.towers else np.zeros_like(w["h"])
    w["z"] = w["bedrock"] + w["soil"]
    w['obstacles'] = np.zeros_like(w['h'], dtype=bool)
    for o in STATE['objects'].values():
        if o['meta']['terrainMode'] == 'TerrainProtected':
            w['obstacles'] |= _core_cells(o['meta'], o['x'], o['y'], o['yaw'])


def _plats(o, base):
    """Platform local -> world (same transform as protection.status / Phase 3 placement_to_world)."""
    c, s = math.cos(math.radians(o["yaw"])), math.sin(math.radians(o["yaw"]))
    return [[o["x"] + p["localPosition"][0] * c - p["localPosition"][1] * s,
             o["y"] + p["localPosition"][0] * s + p["localPosition"][1] * c, base + p["localPosition"][2]]
            for p in o["meta"].get("platforms", [])]


def _objects_state():
    sim = STATE["sim"]
    w = sim.w
    out = []
    for pid, o in STATE["objects"].items():
        core = _core_cells(o["meta"], o["x"], o["y"], o["yaw"])
        towers = [t for t in sim.towers if t.get("pid") == pid]
        if towers:
            st = [protection.status(w, t) for t in towers]
            base = float(np.mean([t["baseZ"] for t in towers]))     # rests on its footing(s)
            flood = max(s["flood_depth_m"] for s in st)
            plats = st[0]["platforms_world"] if len(st) == 1 else _plats(o, base)
        else:
            base = _sample_z(o["x"], o["y"])
            flood = float(w["h"][core].max()) if core.any() else 0.0
            plats = _plats(o, base)
        out.append({"pid": pid, "id": o["id"], "x": o["x"], "y": o["y"], "yaw": o["yaw"], "baseZ": round(base, 4),
                    "submerged": flood > 0.05, "waterDepth": round(flood, 4), "platformsWorld": plats,
                    "terrainMode": o["meta"]["terrainMode"]})
    return out


# ------------------------------------------------------------------ persistence (safe JSON codec)
# No pickle: state is encoded as JSON with explicit tags. Only the allowlisted numerical/weather classes below can
# be reconstructed (by name, via __new__ + __dict__); arrays keep dtype and shape; tuples and
# non-string dict keys are tagged. Decoding never executes code from the save.
from src.ecosystem.cats import Ecology, Population
from src.hydrology.rivers import RiverTracker

_CLASSES = {"Simulation": Simulation, "Ecology": Ecology, "Population": Population, "RiverTracker": RiverTracker, "WeatherGenerator": WeatherGenerator, "Weather": Weather}
_DTYPES = {"float64", "float32", "int64", "int32", "int8", "uint8", "bool", "uint64"}


def _enc(v):
    if isinstance(v, np.ndarray):
        if v.dtype.name not in _DTYPES:
            raise TypeError(f"array dtype {v.dtype} not allowed")
        return {"__nd__": v.dtype.name, "shape": list(v.shape), "b64": base64.b64encode(np.ascontiguousarray(v).tobytes()).decode()}
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    if isinstance(v, tuple):
        return {"__tuple__": [_enc(x) for x in v]}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if isinstance(v, dict):
        if all(isinstance(k, str) for k in v):
            return {"__dict__": {k: _enc(x) for k, x in v.items()}}
        return {"__kdict__": [[_enc(k), _enc(x)] for k, x in v.items()]}
    name = type(v).__name__
    if name in _CLASSES and type(v) is _CLASSES[name]:
        return {"__obj__": name, "attrs": {k: _enc(x) for k, x in v.__dict__.items()}}
    raise TypeError(f"type {type(v)} not allowed in save")


def _dec(v):
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "__nd__" in v:
        if v["__nd__"] not in _DTYPES:
            raise ValueError("bad dtype")
        return np.frombuffer(base64.b64decode(v["b64"]), dtype=np.dtype(v["__nd__"])).reshape(v["shape"]).copy()
    if "__tuple__" in v:
        return tuple(_dec(x) for x in v["__tuple__"])
    if "__dict__" in v:
        return {k: _dec(x) for k, x in v["__dict__"].items()}
    if "__kdict__" in v:
        return {_dec(k): _dec(x) for k, x in v["__kdict__"]}
    if "__obj__" in v:
        cls = _CLASSES.get(v["__obj__"])
        if cls is None:
            raise ValueError("class not allowlisted")
        o = cls.__new__(cls)
        o.__dict__.update({k: _dec(x) for k, x in v["attrs"].items()})
        return o
    raise ValueError("untagged object in save")


def save():
    doc = {"format": "necosmos-v0.10-json", "sim": _enc(STATE["sim"]), "objects": _enc(STATE["objects"]),
           "next_pid": STATE["next_pid"], "params": _enc(STATE["params"]),
           "behavior_events": STATE.get("behavior_events", [])}
    return base64.b64encode(zlib.compress(json.dumps(doc).encode(), 6)).decode("ascii")


def load(b64):
    doc = json.loads(zlib.decompress(base64.b64decode(b64)).decode())
    if doc.get("format") != "necosmos-v0.10-json":
        raise ValueError("not a v0.10 save")
    sim = _dec(doc['sim'])
    objects, params = _dec(doc['objects']), _dec(doc['params'])
    # Older worlds keep all material, cats and placed objects. Weather starts at the
    # saved day; no invented replay of their unrecorded weather history.
    if getattr(sim, 'weather_driver', None) is None:
        sim.cfg['weather'] = load_cfg()['weather']
        driver = WeatherGenerator(sim.seed, sim.clim, sim.cfg['weather'], 'normal')
        season = math.sin((sim.day % 360) / 360 * 2 * math.pi)
        driver.day = sim.day
        driver.current = Weather(sim.day, 0, 0, float(sim.clim['temp_C'] + sim.clim['season_amp_C'] * season),
                                 0.0, float(1 + 0.18 * season), 0.65, 0.0, False)
        sim.weather_driver = driver
        sim.sc['weather_mode'] = 'normal'
        sim.weather_migrated_at = sim.day
        sim.terrain_attribution = {k: np.zeros_like(sim.w['soil']) for k in ('hydro','cat_direct','biogeochemical')}
        sim.terrain_attribution_origin_z = (sim.w['bedrock'] + sim.w['soil']).copy()
        sim._env_cells(sim.day)
    sim.eco.max_population = MAX_POPULATION
    params = dict(params or {}, weatherMode=sim.weather_driver.mode)
    STATE.pop("pending_sim", None)
    STATE.pop("pending_row", None)
    STATE.update(sim=sim, objects=objects, next_pid=int(doc['next_pid']), params=params, behavior_events=doc.get("behavior_events", []))
    return state(include_static=True)


def state_hash():
    return STATE["sim"].state_hash()
