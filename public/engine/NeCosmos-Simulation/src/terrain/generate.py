"""Initial terrain (bedrock, soil) for the five terrain types + helpers. Units: metres.

Grid: N x N cells of cell_m metres, arrays indexed [j, i] (j = +y north, i = +x east).
surface z = bedrock b + soil depth s. The outer ring of cells is the fixed rim: its height
never changes; water/sediment leave the world through the rim's outer faces (open boundary).
"""
import numpy as np

from ..coupling import rng


def value_noise(n, seed, octaves, base_res=4):
    """Deterministic smooth noise in [-1, 1] from counter hashes on coarse lattices."""
    out = np.zeros((n, n))
    total, amp = 0.0, 1.0
    t = (np.arange(n) + 0.5) / n
    for o in range(octaves):
        res = base_res * 2 ** o
        k = np.arange((res + 1) * (res + 1))
        g = (rng.u01(seed, rng.TERRAIN, o, k) * 2 - 1).reshape(res + 1, res + 1)
        pos = t * res
        i0 = np.minimum(pos.astype(int), res - 1)
        f = pos - i0
        f = f * f * (3 - 2 * f)
        a = g[np.ix_(i0, i0)] * (1 - f)[None, :] + g[np.ix_(i0, i0 + 1)] * f[None, :]
        b = g[np.ix_(i0 + 1, i0)] * (1 - f)[None, :] + g[np.ix_(i0 + 1, i0 + 1)] * f[None, :]
        out += amp * (a * (1 - f)[:, None] + b * f[:, None])
        total += amp
        amp *= 0.5
    return out / total


def bell(d, r):
    t = np.clip(d / r, 0, 1)
    return 0.5 * (1 + np.cos(np.pi * t))


def build(terrain_cfg, name, seed):
    """Return dict with bedrock, soil, channel_mask (initial river channel), rim mask."""
    g = terrain_cfg["grid"]
    n, dx = g["n"], g["cell_m"]
    jj, ii = np.mgrid[0:n, 0:n]
    x, y = (ii + 0.5) * dx, (jj + 0.5) * dx
    L = n * dx
    z = np.full((n, n), 1.0)
    channel = np.zeros((n, n), bool)
    centre = []
    s0 = terrain_cfg["soil"]["initial_depth_m"]
    soil = np.full((n, n), s0)
    for op in terrain_cfg["terrains"][name]["ops"]:
        kind = op[0]
        if kind == "noise":
            z += op[1] * value_noise(n, seed, op[2])
        elif kind == "tilt":
            z += op[1] * (x - L / 2) + op[2] * (y - L / 2)
        elif kind == "hill":
            z += op[4] * bell(np.hypot(ii - op[1], jj - op[2]), op[3])
        elif kind == "valley_v":                     # side slope (m/m) rising away from the x centre line
            z += op[1] * np.abs(x - L / 2)
        elif kind == "bowl":
            z -= op[2] * bell(np.hypot(ii - (n - 1) / 2, jj - (n - 1) / 2), op[1])
        elif kind == "channel":                      # carved sinuous channel north -> south, in the soil
            depth, width = op[1], op[2]
            xc = L / 2 + 1.6 * np.sin(y / L * 2.2 * np.pi)
            d = np.abs(x - xc)
            cut = depth * bell(d, width)
            soil = soil - np.minimum(cut, soil - 0.05)
            channel = d < width / 2
            # explicit 1-cell centreline network, north (j=n-1) -> south (j=0), 4-connected
            ic = np.clip(np.round(xc[:, 0] / dx - 0.5).astype(int), 1, n - 2)
            path = []
            for j in range(n - 2, 0, -1):
                if path:
                    pj, pi = path[-1]
                    step = 1 if ic[j] > pi else -1
                    for k in range(pi + step, ic[j] + step, step) if ic[j] != pi else []:
                        path.append((pj, k))            # sideways along the previous row first
                path.append((j, ic[j]))
            centre = path
        else:
            raise ValueError(kind)
    bedrock = z - s0
    rim = np.zeros((n, n), bool)
    rim[0, :] = rim[-1, :] = rim[:, 0] = rim[:, -1] = True
    if name == "initial_river":
        channel &= ~rim
    return {"bedrock": bedrock, "soil": soil, "channel_mask": channel, "rim": rim, "x": x, "y": y, "dx": dx,
            "centreline": centre}


def unlock_masks(n, levels, initial_fraction):
    """Nested unlock masks with exact areas k * initial_fraction * n^2 (k = 1..levels).
    Cells are ranked by Chebyshev distance from the centre, ties by Euclidean distance then
    index, so each level is a near-square centred region with exactly the target cell count."""
    jj, ii = np.mgrid[0:n, 0:n]
    c = (n - 1) / 2
    cheb = np.maximum(np.abs(ii - c), np.abs(jj - c))
    eu = np.hypot(ii - c, jj - c)
    order = np.lexsort((np.arange(n * n), eu.ravel(), cheb.ravel()))
    masks = []
    for k in range(1, levels + 1):
        m = np.zeros(n * n, bool)
        m[order[:int(round(k * initial_fraction * n * n))]] = True
        masks.append(m.reshape(n, n))
    return masks
