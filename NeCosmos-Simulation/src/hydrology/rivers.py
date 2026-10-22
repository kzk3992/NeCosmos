"""River / pond classification from flow history (not from cumulative-day labels).

Per day, from the hydrology output:
  Qema    exponential moving average of daily outflow volume (tau days)
  dirEMA  EMA of outflow per direction (E, W, N, S, outside) -> downstream pointer = argmax
Candidate river cell: Qema >= q_on (enter) / stays while Qema >= q_off (hysteresis), AND
concentrated: Qema >= conc * mean Qema of the two lateral neighbours (perpendicular to the
downstream direction), so uniform sheet flow is never a river. A cell becomes "river" after
persist_on consecutive candidate days and stops after persist_off consecutive non-candidate days.
Rivers = weakly connected components of river cells linked by downstream pointers; a component is
accepted only if its longest directed path >= min_river_cells (fragments rejected; no fallback).
Ponds = cells with depth >= pond_depth and Qema/(h*A) < pond_velocity_ratio (still water),
4-connected components; pond cells are never river cells.
"""
import numpy as np

DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]   # (dj, di) for E, W, N, S


class RiverTracker:
    def __init__(self, shape, cfg, channel_mask, initial_surface):
        r = cfg["river"]
        self.cfg = r
        self.alpha = 1.0 / r["ema_tau_days"]
        self.Qema = np.zeros(shape)
        self.dirEma = np.zeros((5,) + shape)
        self.on_count = np.zeros(shape, int)
        self.off_count = np.zeros(shape, int)
        self.river = np.zeros(shape, bool)
        self.channel_mask = channel_mask
        self.z0 = initial_surface.copy()
        self.prev_river = np.zeros(shape, bool)
        self.prev_down = None
        self.events = {"first_concentration_day": None, "first_incised_groove_day": None,
                       "first_connected_river_day": None, "first_natural_river_day": None,
                       "max_river_length": 0, "max_natural_river_length": 0, "reroutes": 0,
                       "max_daily_river_cell_change": 0, "first_pond_day": None, "max_pond_area_m2": 0.0,
                       "pond_overflow_days": 0, "pond_river_connected_days": 0}

    def initialize_existing(self, path, shape, q):
        """Day-0 existing river (explicit initial condition, not emergence): flow history Qema = q and the
        river flag on an explicit 4-connected path; each cell points to the next path cell, the last
        one points outside (south rim)."""
        mask = np.zeros(shape, bool)
        for k, (j, i) in enumerate(path):
            mask[j, i] = True
            self.Qema[j, i] = q
            if k + 1 < len(path):
                nj, ni = path[k + 1]
                d = DIRS.index((nj - j, ni - i))
            else:
                d = 3 if j == 1 else 4
            self.dirEma[d, j, i] = q
        self.river[mask] = True
        self.on_count[mask] = self.cfg["persist_on_days"]
        self.preexisting = mask
        self.events["preexisting_river_day0_cells"] = int(mask.sum())
        return mask

    def update(self, day, Q, dirs, h, z, A, conc=1.5):
        r = self.cfg
        a = self.alpha
        self.Qema = (1 - a) * self.Qema + a * Q
        self.dirEma = (1 - a) * self.dirEma + a * dirs
        down = np.argmax(self.dirEma, axis=0)            # 0..3 neighbour, 4 = outside
        # lateral concentration
        lat = np.zeros_like(self.Qema)
        Qp = np.pad(self.Qema, 1, mode="edge")
        n0, n1 = self.Qema.shape
        e = Qp[1:-1, 2:]
        w = Qp[1:-1, :-2]
        nn = Qp[2:, 1:-1]
        s = Qp[:-2, 1:-1]
        ew = (down == 0) | (down == 1)                   # flowing E/W -> lateral are N/S
        lat = np.where(ew, (nn + s) / 2, (e + w) / 2)
        concentrated = self.Qema >= conc * np.maximum(lat, 1e-12)
        pond = (h >= r["pond_depth_m"]) & (self.Qema / np.maximum(h * A, 1e-12) < r["pond_velocity_ratio"])
        # pond wins immediately: a still pond cell can never hold (or keep) a river flag
        self.river &= ~pond
        thr = np.where(self.river, r["q_off_m3_day"], r["q_on_m3_day"])
        cand = (self.Qema >= thr) & ~pond      # flow-bearing; concentration is required of anchors (below)
        self.on_count = np.where(cand, self.on_count + 1, 0)
        self.off_count = np.where(cand, 0, self.off_count + 1)
        self.river = np.where(self.river, self.off_count < r["persist_off_days"], self.on_count >= r["persist_on_days"]) & ~pond
        # flowing today (net flux) vs dormant channel (flag kept by hysteresis but no current flow)
        flowing = self.river & (Q >= r["flow_min_today_frac"] * r["q_off_m3_day"])
        dormant = self.river & ~flowing
        if self.events["first_concentration_day"] is None and ((self.Qema >= r["q_on_m3_day"]) & concentrated).any():
            self.events["first_concentration_day"] = day
        incised = (self.z0 - z) >= r["incision_m"]
        natural_cells = incised & ~self.channel_mask
        if self.events["first_incised_groove_day"] is None and (natural_cells & (self.Qema >= r["q_off_m3_day"])).any():
            self.events["first_incised_groove_day"] = day
        comps = self._components(down, flowing)
        anchors = concentrated & flowing
        for cmp in comps:
            cmp["anchor_frac"] = float(np.mean([anchors[c] for c in cmp["cells"]]))
            cmp["width_ratio"] = len(cmp["cells"]) / max(cmp["length"], 1)
        valid = [cmp for cmp in comps if not cmp["cyclic"] and cmp["length"] >= r["min_river_cells"]
                 and cmp["anchor_frac"] >= r.get("anchor_frac_min", 0.0) and cmp["width_ratio"] <= r.get("max_width_ratio", 1e9)]
        mask_valid = np.zeros_like(self.river)
        for cmp in valid:
            for (j, i) in cmp["cells"]:
                mask_valid[j, i] = True
        natural = [cmp for cmp in valid if np.mean([natural_cells[j, i] for j, i in cmp["cells"]]) >= 0.5]
        L = max([cmp["length"] for cmp in valid], default=0)
        Ln = max([cmp["length"] for cmp in natural], default=0)
        ev = self.events
        if valid and ev["first_connected_river_day"] is None:
            ev["first_connected_river_day"] = day
        if natural and ev["first_natural_river_day"] is None:
            ev["first_natural_river_day"] = day
        ev["max_river_length"] = max(ev["max_river_length"], L)
        ev["max_natural_river_length"] = max(ev["max_natural_river_length"], Ln)
        change = int((mask_valid != self.prev_river).sum())
        ev["max_daily_river_cell_change"] = max(ev["max_daily_river_cell_change"], change)
        if self.prev_down is not None:
            both = mask_valid & self.prev_river
            ev["reroutes"] += int((both & (down != self.prev_down)).sum())
        self.prev_river = mask_valid
        self.prev_down = down
        # ponds
        pcomps = _label4(pond)
        parea = float(pond.sum() * A)
        if pcomps and ev["first_pond_day"] is None:
            ev["first_pond_day"] = day
        ev["max_pond_area_m2"] = max(ev["max_pond_area_m2"], parea)
        # overflow = today's outflow from pond cells into non-pond cells (or outside), m^3
        spill = float((dirs[4] * pond).sum())
        for d, (dj, di) in enumerate(DIRS):
            nb = np.roll(np.roll(pond, -dj, 0), -di, 1)          # neighbour in direction d is pond?
            spill += float((dirs[d] * pond * ~nb).sum())
        overflow = spill > r.get("overflow_m3_day", 0.02)
        ev["pond_overflow_days"] += int(overflow)
        connected = bool((_dilate(pond) & mask_valid).any())
        ev["pond_river_connected_days"] += int(connected)
        dir_counts = np.bincount(down[mask_valid], minlength=5) if mask_valid.any() else np.zeros(5, int)
        pre = getattr(self, "preexisting", np.zeros_like(mask_valid))
        return {"river_cells": int(mask_valid.sum()), "preexisting_river_cells": int((mask_valid & pre).sum()), "river_components": len(valid), "river_longest": L,
                "natural_river_cells": int(sum(len(c["cells"]) for c in natural)), "natural_river_longest": Ln,
                "candidate_cells": int(self.river.sum()), "dormant_channel_cells": int(dormant.sum()),
                "rejected_fragments": sum(1 for c in comps if not c["cyclic"] and c["length"] < r["min_river_cells"]),
                "rejected_sheet": sum(1 for c in comps if not c["cyclic"] and c["length"] >= r["min_river_cells"]
                                      and (c["anchor_frac"] < r.get("anchor_frac_min", 0.0) or c["width_ratio"] > r.get("max_width_ratio", 1e9))),
                "rejected_cyclic": sum(1 for c in comps if c["cyclic"]), "pond_spill_m3": spill,
                "river_dir_E": int(dir_counts[0]), "river_dir_W": int(dir_counts[1]), "river_dir_N": int(dir_counts[2]),
                "river_dir_S": int(dir_counts[3]), "river_dir_out": int(dir_counts[4]), "river_change": change,
                "pond_count": len(pcomps), "pond_area_m2": parea,
                "pond_volume_m3": float((h * pond).sum() * A), "pond_max_depth_m": float(h[pond].max()) if pond.any() else 0.0,
                "pond_overflow": int(overflow), "pond_river_connected": int(connected)}, mask_valid, pond, down

    def _components(self, down, mask):
        """Weakly connected components of `mask` cells linked by downstream pointers. Each gets
        cyclic (any pointer cycle inside -> rejected as a river) and length = longest acyclic
        directed path (pointers form a functional graph, so every acyclic path ends by leaving
        the river set: outside, pond, or a non-river cell)."""
        idx = np.argwhere(mask)
        if len(idx) == 0:
            return []
        cells = {tuple(p) for p in idx}

        def nxt(c):
            d = down[c]
            if d == 4:
                return None
            dj, di = DIRS[d]
            t = (c[0] + dj, c[1] + di)
            return t if t in cells else None
        succ = {c: nxt(c) for c in cells}
        # functional-graph cycle detection (white/grey/black colouring)
        state, on_cycle = {}, set()
        for c in sorted(cells):
            path, u = [], c
            while u is not None and u not in state:
                state[u] = 1
                path.append(u)
                u = succ[u]
            if u is not None and state.get(u) == 1:          # closed a new cycle
                k = path.index(u)
                on_cycle.update(path[k:])
            for v in path:
                state[v] = 2
        length = {}

        def plen(u):
            stack = []
            while u is not None and u not in length and u not in on_cycle:
                stack.append(u)
                u = succ[u]
            base = 0 if (u is None or u in on_cycle) else length[u]
            if u in on_cycle:
                base = -10 ** 6                                   # path runs into a loop: invalid
            for v in reversed(stack):
                base = base + 1
                length[v] = base
            return length.get(stack[0], base) if stack else base
        adj = {c: set() for c in cells}
        for c, t in succ.items():
            if t is not None:
                adj[c].add(t)
                adj[t].add(c)
        seen, comps = set(), []
        for c in sorted(cells):
            if c in seen:
                continue
            stack, comp = [c], []
            seen.add(c)
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in adj[u]:
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            cyclic = any(u in on_cycle for u in comp)
            best = 0 if cyclic else max(plen(u) for u in comp)
            comps.append({"cells": comp, "length": max(best, 0), "cyclic": cyclic})
        return comps


def _dilate(m):
    d = m.copy()
    d[1:, :] |= m[:-1, :]
    d[:-1, :] |= m[1:, :]
    d[:, 1:] |= m[:, :-1]
    d[:, :-1] |= m[:, 1:]
    return d


def _label4(mask):
    n0, n1 = mask.shape
    lab = np.zeros(mask.shape, int)
    comps = []
    for j0, i0 in np.argwhere(mask):
        if lab[j0, i0]:
            continue
        k = len(comps) + 1
        stack = [(j0, i0)]
        lab[j0, i0] = k
        cnt = 0
        while stack:
            j, i = stack.pop()
            cnt += 1
            for dj, di in DIRS:
                jj, ii = j + dj, i + di
                if 0 <= jj < n0 and 0 <= ii < n1 and mask[jj, ii] and not lab[jj, ii]:
                    lab[jj, ii] = k
                    stack.append((jj, ii))
        comps.append(cnt)
    return comps
