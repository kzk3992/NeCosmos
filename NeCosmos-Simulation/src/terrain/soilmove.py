"""Soil transfer primitives that share ONE daily height-change budget per cell.

Every process that changes a cell's soil (hydraulic erosion/deposition, creep, cat digging,
fish resuspension, humification) charges its absolute volume change to st["dz_used"] (m, reset
each day). A cell may change by at most max_dz_per_day (gross, so |net dz| is also bounded).
Lateral transfers are scaled per face by min(budget scale of donor, budget scale of receiver,
donor soil availability) and by (1 - max protection of the two cells); the unmoved part simply
stays at the donor. Nothing is discarded.
"""
import numpy as np


def remaining(st):
    return np.maximum(st["max_dz"] - st["dz_used"], 0.0) * st["A"]          # m^3 per cell


def transfer_faces(st, qx, qy, frozen=None):
    """Move soil between 4-neighbours. qx[j, i] > 0 moves from (j, i+1) to (j, i); qy[j, i] > 0
    moves from (j+1, i) to (j, i). Returns total moved volume (m^3)."""
    A = st["A"]
    prot = st["protection"]
    px = 1 - np.maximum(prot[:, 1:], prot[:, :-1])
    py = 1 - np.maximum(prot[1:, :], prot[:-1, :])
    qx = qx * px
    qy = qy * py
    if frozen is not None:
        qx = np.where(frozen[:, 1:] | frozen[:, :-1], 0.0, qx)
        qy = np.where(frozen[1:, :] | frozen[:-1, :], 0.0, qy)
    out = np.zeros_like(st["soil"])
    gross = np.zeros_like(out)
    for q, ax in ((qx, 1), (qy, 0)):
        pos, neg = np.maximum(q, 0), np.maximum(-q, 0)
        if ax == 1:
            out[:, 1:] += pos
            out[:, :-1] += neg
            gross[:, 1:] += pos + neg
            gross[:, :-1] += pos + neg
        else:
            out[1:, :] += pos
            out[:-1, :] += neg
            gross[1:, :] += pos + neg
            gross[:-1, :] += pos + neg
    bud = np.where(gross > 0, np.minimum(1.0, remaining(st) / np.maximum(gross, 1e-300)), 1.0)
    soil = np.where(out > 0, np.minimum(1.0, st["soil"] * A / np.maximum(out, 1e-300)), 1.0)
    fx = np.minimum(bud[:, 1:], bud[:, :-1])
    fy = np.minimum(bud[1:, :], bud[:-1, :])
    qx = np.where(qx > 0, qx * np.minimum(fx, soil[:, 1:]), qx * np.minimum(fx, soil[:, :-1]))
    qy = np.where(qy > 0, qy * np.minimum(fy, soil[1:, :]), qy * np.minimum(fy, soil[:-1, :]))
    dv = np.zeros_like(out)
    g = np.zeros_like(out)
    dv[:, :-1] += qx
    dv[:, 1:] -= qx
    dv[:-1, :] += qy
    dv[1:, :] -= qy
    g[:, :-1] += np.abs(qx)
    g[:, 1:] += np.abs(qx)
    g[:-1, :] += np.abs(qy)
    g[1:, :] += np.abs(qy)
    new = st["soil"] + dv / A
    assert new.min() >= -1e-12, f"soil transfer drove soil negative ({new.min()})"
    st["roundoff"]["soil"] += float(-np.minimum(new, 0).sum() * A)
    st["soil"] = np.maximum(new, 0.0)
    st["dz_used"] = st["dz_used"] + g / A
    return float(np.abs(qx).sum() + np.abs(qy).sum())


def local_exchange(st, want_vol, direction):
    """Cell-local soil<->sediment exchange limited by the budget (and soil for erosion).
    direction +1: soil -> sediment (erosion), -1: sediment -> soil (deposition). Returns applied."""
    A = st["A"]
    v = np.minimum(want_vol, remaining(st))
    if direction > 0:
        v = np.minimum(v, st["soil"] * A)
        st["soil"] = st["soil"] - v / A
        st["sed"] = st["sed"] + v
    else:
        v = np.minimum(v, st["sed"])
        st["soil"] = st["soil"] + v / A
        st["sed"] = st["sed"] - v
    st["dz_used"] = st["dz_used"] + v / A
    return v


def exfiltrate(st, fc):
    """Soil water above field capacity (fc * soil depth * retention) returns to the surface."""
    cap = fc * st["soil"] * st["retention"]
    ex = np.maximum(st["Ws"] - cap, 0.0)
    st["Ws"] = st["Ws"] - ex
    st["h"] = st["h"] + ex
    return float(ex.sum() * st["A"])
