"""Tower footprints, smooth protection buffers, grounding and flood state.

Tower geometry is read (read-only) from Phase 3 metadata NeCosmos-Assets/objects/metadata/*.json.
World placement: (x, y) metres, yaw degrees CCW about +Z. Local (lx, ly, lz) -> world
  (x + lx cos - ly sin, y + lx sin + ly cos, baseZ + lz)
Protection p in [0, strength]: full on cells whose centre lies in the footprint grown by half a cell,
smoothstep falloff over bufferRadius. Soil transfers touching a cell are multiplied by (1 - p);
the rejected part stays at the donor (nothing is moved elsewhere or deleted).
Placement flattens the core to its mean surface by moving soil only within the core (volume
neutral; soil never below 0 - if the bedrock pokes above the mean, the fill is scaled down and the
shortfall recorded instead of inventing soil).
"""
import json
import math

import numpy as np


def load_tower(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def footprint_distance(x, y, tw, dx):
    c, s = math.cos(math.radians(tw["yaw"])), math.sin(math.radians(tw["yaw"]))
    lx = (x - tw["x"]) * c + (y - tw["y"]) * s
    ly = -(x - tw["x"]) * s + (y - tw["y"]) * c
    hw = tw["meta"]["footprint"]["width"] / 2 + dx / 2
    hd = tw["meta"]["footprint"]["depth"] / 2 + dx / 2
    return np.hypot(np.maximum(np.abs(lx) - hw, 0), np.maximum(np.abs(ly) - hd, 0))


def protection_field(x, y, towers, dx):
    p = np.zeros_like(x)
    for tw in towers:
        pr = tw["meta"]["protection"]
        d = footprint_distance(x, y, tw, dx)
        t = np.clip(1 - d / max(pr["bufferRadius"], 1e-9), 0, 1)
        p = np.maximum(p, pr["strength"] * np.where(d <= 0, 1.0, t * t * (3 - 2 * t)))
    return p


def place(w, tw):
    core = footprint_distance(w["x"], w["y"], tw, w["dx"]) <= 0
    z = w["bedrock"] + w["soil"]
    zbar = float(z[core].mean())
    want = np.maximum(zbar - w["bedrock"][core], 0.0)
    have = w["soil"][core]
    if want.sum() > have.sum() + 1e-15:          # bedrock above the mean: cannot invent soil
        want = want * (have.sum() / want.sum())
    tw["flatten_shortfall_m3"] = float(max(np.maximum(zbar - w["bedrock"][core], 0).sum() - have.sum(), 0) * w["A"])
    w["soil"][core] = want
    tw["core"] = core
    tw["baseZ"] = float((w["bedrock"] + w["soil"])[core].mean())
    return tw


def status(w, tw):
    core = tw["core"]
    z = w["bedrock"] + w["soil"]
    base = float(z[core].mean())
    tw["baseZ"] = base
    err = float(np.abs(z[core] - base).max())
    flood = float(w["h"][core].max())
    plats = []
    c, s = math.cos(math.radians(tw["yaw"])), math.sin(math.radians(tw["yaw"]))
    for p in tw["meta"]["platforms"]:
        lx, ly, lz = p["localPosition"]
        plats.append([tw["x"] + lx * c - ly * s, tw["y"] + lx * s + ly * c, base + lz])
    return {"ground_error_m": err, "flood_depth_m": flood, "flooded": flood > 0.05, "platforms_world": plats}
