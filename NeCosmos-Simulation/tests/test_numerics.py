"""Stage 1 unit / numerical tests (stdlib unittest + numpy).

  python3 -m unittest discover -s tests -v
Includes regression tests for the six independent-review concerns (reports/codex_review_notes.md):
R1 combined daily dz bound (steep + converging donors), R2 soil water above capacity, R3 cyclic
river components, R4 river/pond exclusivity + dormant channels, R5 hydrostatic lake net vs gross
flux + substep sensitivity, R6 clamps only absorb roundoff.
"""
import copy
import json
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.coupling import rng  # noqa: E402
from src.coupling.simulation import Simulation, load_cfg  # noqa: E402
from src.hydrology import rivers, water  # noqa: E402
from src.terrain import generate, protection, soilmove  # noqa: E402

CFG = load_cfg()
TC = CFG["terrain"]


def bare_world(n=12, dx=0.5, z=None, soil=0.4, closed=False, max_dz=0.02):
    A = dx * dx
    jj, ii = np.mgrid[0:n, 0:n]
    edge = np.zeros((n, n))
    if not closed:
        edge[0, :] += 1
        edge[-1, :] += 1
        edge[:, 0] += 1
        edge[:, -1] += 1
    rim = np.zeros((n, n), bool)
    rim[0, :] = rim[-1, :] = rim[:, 0] = rim[:, -1] = True
    zz = np.ones((n, n)) if z is None else z
    return {"A": A, "dx": dx, "rim": rim, "edge_faces": edge, "bedrock": zz - soil, "soil": np.full((n, n), soil),
            "h": np.zeros((n, n)), "Ws": np.zeros((n, n)), "sed": np.zeros((n, n)), "cover": np.zeros((n, n)),
            "hardness": np.zeros((n, n)), "retention": np.ones((n, n)), "evap_mult": np.ones((n, n)),
            "protection": np.zeros((n, n)), "dz_used": np.zeros((n, n)), "max_dz": max_dz, "snow": np.zeros((n, n)),
            "roundoff": {"soil": 0.0, "sed": 0.0, "water_h": 0.0}, "x": (ii + 0.5) * dx, "y": (jj + 0.5) * dx}


def tcfg(**kw):
    c = copy.deepcopy(TC)
    for k, v in kw.items():
        sec, key = k.split("__")
        c[sec][key] = v
    return c


def storage(w):
    return float((w["h"].sum() + w["Ws"].sum() + w["snow"].sum()) * w["A"]), float(w["soil"].sum() * w["A"] + w["sed"].sum())


class TestRNGAndCoordinates(unittest.TestCase):
    def test_rng_known_values_and_independence(self):
        a = rng.hash32(1, 2, 3, [0, 1, 2])
        self.assertEqual(a.tolist(), rng.hash32(1, 2, 3, [0, 1, 2]).tolist())
        # order independence: drawing index 2 alone gives the same value
        self.assertEqual(int(rng.hash32(1, 2, 3, [2])[0]), int(a[2]))
        self.assertTrue((rng.u01(5, 1, 1, np.arange(1000)) < 1).all())
        u = rng.u01(9, 1, 1, np.arange(20000))
        self.assertAlmostEqual(float(u.mean()), 0.5, delta=0.01)

    def test_unlock_area_exact(self):
        ms = generate.unlock_masks(32, 4, 0.25)
        self.assertEqual([int(m.sum()) for m in ms], [256, 512, 768, 1024])
        for a, b in zip(ms, ms[1:]):
            self.assertFalse((a & ~b).any())

    def test_tower_local_to_world(self):
        meta = protection.load_tower(os.path.join(os.path.dirname(ROOT), "NeCosmos-Assets", "objects", "metadata", "cat_tower_01.json"))
        w = bare_world(n=32)
        w["bedrock"] = np.zeros((32, 32))
        tw = protection.place(w, {"x": 8.0, "y": 7.0, "yaw": 90.0, "meta": meta})
        stt = protection.status(w, tw)
        lx, ly, lz = meta["platforms"][0]["localPosition"]
        self.assertTrue(np.allclose(stt["platforms_world"][0], [8.0 - ly, 7.0 + lx, tw["baseZ"] + lz]))
        self.assertLess(stt["ground_error_m"], 1e-12)


class TestWater(unittest.TestCase):
    def bowl(self, closed):
        n = 16
        jj, ii = np.mgrid[0:n, 0:n]
        z = 1.0 - 0.4 * generate.bell(np.hypot(ii - 7.5, jj - 7.5), 7)
        return bare_world(n=n, z=z, closed=closed, soil=0.2)

    def test_closed_conservation(self):
        w = self.bowl(closed=True)
        cfg = tcfg()
        w0, s0 = storage(w)
        tot_rain = tot_e = 0.0
        for d in range(60):
            out = water.daily(w, cfg, 0.03 if d < 20 else 0.0, 0.002)
            led = out["ledger"]
            tot_rain += led["rain"]
            tot_e += led["evap_surface"] + led["evap_soil"]
            self.assertEqual(led["outflow"], 0.0)
        w1, s1 = storage(w)
        self.assertAlmostEqual(w1 - w0, tot_rain - tot_e, delta=1e-10)
        self.assertAlmostEqual(s1, s0, delta=1e-10)
        self.assertTrue(np.isfinite(w["h"]).all() and w["h"].min() >= 0)

    def test_bowl_fill_spill_dry(self):
        w = self.bowl(closed=False)
        cfg = tcfg()
        out_tot, levels = 0.0, []
        for d in range(120):
            out = water.daily(w, cfg, 0.08, 0.0)                   # storm: fill and spill
            out_tot += out["ledger"]["outflow"]
            levels.append(float(w["h"].max()))
        self.assertGreater(w["h"][8, 8], 0.2)                       # pond stored in the bowl
        self.assertGreater(out_tot, 0.0)                            # spill reached the open rim
        area_wet = int((w["h"] > 0.05).sum())
        for d in range(400):
            water.daily(w, cfg, 0.0, 0.006)                         # drought
        self.assertLess(int((w["h"] > 0.05).sum()), area_wet)       # shrinks
        for d in range(800):
            water.daily(w, cfg, 0.0, 0.006)
        self.assertEqual(int((w["h"] > 0.05).sum()), 0)             # dries

    def test_R5_hydrostatic_lake_net_vs_gross_and_substeps(self):
        n = 14
        rngv = generate.value_noise(n, 3, 2)
        z = 1.0 + 0.05 * rngv
        res = {}
        with self.assertRaises(AssertionError):                       # unstable substep count is refused
            water.daily(bare_world(n=4), tcfg(hydrology__substeps=6), 0.0, 0.0)
        for nsub in (12, 24, 48):
            w = bare_world(n=n, z=z, closed=True, soil=0.3)
            w["Ws"][:] = TC["soil"]["field_capacity"] * 0.3            # full soil: no infiltration
            level = float(z.max()) + 0.2
            w["h"] = level - z
            w["h"][5, 5] += 0.05                                        # perturbation
            cfg = tcfg(hydrology__substeps=nsub)
            gross = net = 0.0
            for d in range(40):
                o = water.daily(w, cfg, 0.0, 0.0, erosion=False)
                gross, net = float(o["Q_gross"].sum()), float(o["Q"].sum())
            H = w["bedrock"] + w["soil"] + w["h"]
            res[nsub] = H.copy()
            self.assertLess(float(H.std()), 1e-4, f"lake not level for substeps={nsub}")
            self.assertLessEqual(net, gross + 1e-15)
            self.assertLess(net, 1e-4)                                   # no sustained apparent throughflow
        self.assertLess(float(np.abs(res[12] - res[48]).max()), 1e-3)    # substep sensitivity small

    def test_R5_river_tracker_ignores_lake(self):
        n = 14
        z = 1.0 + 0.05 * generate.value_noise(n, 3, 2)
        w = bare_world(n=n, z=z, closed=True, soil=0.3)
        w["Ws"][:] = TC["soil"]["field_capacity"] * 0.3
        w["h"] = float(z.max()) + 0.2 - z
        tr = rivers.RiverTracker((n, n), TC, np.zeros((n, n), bool), z)
        for d in range(1, 80):
            o = water.daily(w, TC, 0.0, 0.0, erosion=False)
            r, mask, pond, _ = tr.update(d, o["Q"], o["dirs"], w["h"], w["bedrock"] + w["soil"], w["A"])
        self.assertEqual(r["river_cells"], 0)
        self.assertGreater(r["pond_count"], 0)

    def test_R2_soil_water_exfiltrates_when_soil_lost(self):
        w = bare_world(n=8, soil=0.3, closed=True)
        fc = TC["soil"]["field_capacity"]
        w["Ws"][:] = fc * 0.3                                           # saturated to field capacity
        w0, s0 = storage(w)
        w["soil"][2:6, 2:6] = 0.01                                      # near-complete soil loss (moved into sediment)
        w["sed"][2:6, 2:6] += (0.3 - 0.01) * w["A"]
        w["retention"][:] = 0.8                                         # retention bonus removed as well
        ex = soilmove.exfiltrate(w, fc)
        self.assertGreater(ex, 0)
        self.assertTrue((w["Ws"] <= fc * w["soil"] * w["retention"] + 1e-15).all())
        w1, s1 = storage(w)
        self.assertAlmostEqual(w1, w0, delta=1e-12)                     # displaced, not deleted
        self.assertAlmostEqual(s1, s0, delta=1e-12)

    def test_R6_clamp_rejects_substantive_negative(self):
        w = bare_world(n=4)
        with self.assertRaises(AssertionError):
            water._clamp(np.array([1.0, -1e-6]), w, "sed", 1.0)
        out = water._clamp(np.array([1.0, -1e-15]), w, "sed", 1.0)
        self.assertEqual(out.min(), 0.0)
        self.assertGreater(w["roundoff"]["sed"], 0)


class TestSediment(unittest.TestCase):
    def tilted(self, max_dz=0.02, soil=0.3):
        n = 16
        jj, ii = np.mgrid[0:n, 0:n]
        z = 1.0 + 0.08 * jj * 0.5                                        # 8% slope draining south (j=0)
        z[0, :] = z[1, :] - 0.01
        return bare_world(n=n, z=z, soil=soil, max_dz=max_dz)

    def test_erosion_transport_deposition_conserved(self):
        w = self.tilted()
        b0 = w["bedrock"].copy()
        w0, s0 = storage(w)
        exp = 0.0
        e = d = 0.0
        for day in range(30):
            o = water.daily(w, TC, 0.06, 0.001)
            exp += o["ledger"]["sed_export"]
            e += o["ledger"]["eroded"]
            d += o["ledger"]["deposited"]
        w1, s1 = storage(w)
        self.assertGreater(e, 0)
        self.assertGreater(d, 0)
        self.assertAlmostEqual(s1 - s0, -exp, delta=1e-10)                # only boundary export leaves
        self.assertTrue(np.array_equal(w["bedrock"], b0))                  # bedrock untouched
        self.assertGreaterEqual(float(w["soil"].min()), 0.0)

    def test_R1_combined_dz_bound_steep_converging(self):
        n = 12
        jj, ii = np.mgrid[0:n, 0:n]
        z = 1.0 + 0.9 * np.hypot(ii - 5.5, jj - 5.5) * 0.5                # steep cone pit: all donors converge
        w = bare_world(n=n, z=z, soil=0.5, max_dz=0.01)
        cfg = tcfg(sediment__creep_coeff=0.2, sediment__k_erode=5.0, sediment__repose_slope=0.3)
        w0, s0 = storage(w)
        exported = 0.0
        for day in range(20):
            w["dz_used"] = np.zeros((n, n))
            zs = w["bedrock"] + w["soil"]
            o = water.daily(w, cfg, 0.1, 0.0)
            exported += o["ledger"]["sed_export"]
            water.creep(w, cfg)
            dig = np.full((n, n), 0.002)                                  # heavy digging everywhere
            soilmove.transfer_faces(w, dig[:, 1:] / 4 - dig[:, :-1] / 4, dig[1:, :] / 4 - dig[:-1, :] / 4, frozen=w["rim"])
            v = soilmove.local_exchange(w, np.full((n, n), 0.01), +1)      # resuspension request
            dz = np.abs(w["bedrock"] + w["soil"] - zs)
            self.assertLessEqual(float(w["dz_used"].max()), 0.01 + 1e-12)
            self.assertLessEqual(float(dz.max()), 0.01 + 1e-12)
        w1, s1 = storage(w)
        self.assertAlmostEqual(s1 - s0, -exported, delta=1e-10)           # throttled, never discarded

    def test_protection_rejects_and_releases(self):
        meta = protection.load_tower(os.path.join(os.path.dirname(ROOT), "NeCosmos-Assets", "objects", "metadata", "cat_tower_01.json"))
        w = self.tilted(soil=0.3)
        tw = protection.place(w, {"x": 4.0, "y": 4.0, "yaw": 0.0, "meta": meta})
        w["protection"] = protection.protection_field(w["x"], w["y"], [tw], w["dx"])
        core = tw["core"]
        s_core = w["soil"][core].copy()
        w0, s0 = storage(w)
        exp = 0.0
        for day in range(30):
            w["dz_used"][:] = 0
            o = water.daily(w, TC, 0.06, 0.0)
            exp += o["ledger"]["sed_export"]
            water.creep(w, TC)
        moved_core = float(np.abs(w["soil"][core] - s_core).max())
        self.assertLess(moved_core, 0.05 * 0.02 * 30 + 1e-9)
        w1, s1 = storage(w)
        self.assertAlmostEqual(s1 - s0, -exp, delta=1e-10)
        w["protection"][:] = 0                                            # removal releases
        before = w["soil"][core].copy()
        for day in range(10):
            w["dz_used"][:] = 0
            water.daily(w, TC, 0.06, 0.0)
        self.assertGreater(float(np.abs(w["soil"][core] - before).max()), 0.0)


class TestRivers(unittest.TestCase):
    def tracker(self, n=12, **kw):
        cfg = copy.deepcopy(TC)
        cfg["river"].update(dict(persist_on_days=1, persist_off_days=3, ema_tau_days=1), **kw)
        return rivers.RiverTracker((n, n), cfg, np.zeros((n, n), bool), np.ones((n, n)))

    def feed(self, tr, Q, dirs, h=None, days=3):
        n = Q.shape[0]
        h = np.zeros((n, n)) if h is None else h
        for d in range(1, days + 1):
            r, mask, pond, down = tr.update(d, Q, dirs, h, np.ones((n, n)), 0.25)
        return r, mask, pond

    def path(self, cells, n=12, q=1.0, closed_loop=False):
        Q = np.zeros((n, n))
        dirs = np.zeros((5, n, n))
        for k, (j, i) in enumerate(cells):
            nxt = cells[(k + 1) % len(cells)] if (closed_loop or k + 1 < len(cells)) else None
            Q[j, i] = q
            if nxt is None:
                dirs[4, j, i] = q
            else:
                dj, di = nxt[0] - j, nxt[1] - i
                dirs[{(0, 1): 0, (0, -1): 1, (1, 0): 2, (-1, 0): 3}[(dj, di)], j, i] = q
        return Q, dirs

    def test_connected_path_accepted_fragment_rejected(self):
        tr = self.tracker()
        Q, dirs = self.path([(6, i) for i in range(1, 9)])
        r, mask, _ = self.feed(tr, Q, dirs)
        self.assertEqual(r["river_components"], 1)
        self.assertEqual(r["river_longest"], 8)
        tr = self.tracker()
        Q, dirs = self.path([(6, i) for i in range(1, 4)])
        r, mask, _ = self.feed(tr, Q, dirs)
        self.assertEqual(r["river_components"], 0)
        self.assertEqual(r["rejected_fragments"], 1)

    def test_disconnected_labels_not_merged(self):
        tr = self.tracker()
        Q1, d1 = self.path([(3, i) for i in range(1, 5)])
        Q2, d2 = self.path([(8, i) for i in range(5, 9)])
        r, mask, _ = self.feed(tr, Q1 + Q2, d1 + d2)
        self.assertEqual(r["river_components"], 0)                         # two 4-cell fragments, not one 8-cell river

    def test_R3_cycle_rejected(self):
        loop = [(4, 4), (4, 5), (4, 6), (5, 6), (6, 6), (6, 5), (6, 4), (5, 4)]
        tr = self.tracker()
        Q, dirs = self.path(loop, closed_loop=True)
        r, mask, _ = self.feed(tr, Q, dirs)
        self.assertEqual(r["river_components"], 0)
        self.assertEqual(r["rejected_cyclic"], 1)
        # direction reversal: EMA direction flips; reversed straight path still one acyclic river
        tr = self.tracker()
        Q, dirs = self.path([(6, i) for i in range(1, 9)])
        self.feed(tr, Q, dirs)
        Q, dirs = self.path([(6, i) for i in range(8, 0, -1)])
        r, mask, _ = self.feed(tr, Q, dirs * 5, days=5)
        self.assertEqual(r["rejected_cyclic"], 0)
        self.assertEqual(r["river_longest"], 8)

    def test_all_sheet_flow_is_not_a_river(self):
        tr = self.tracker()
        n = 12
        Q = np.ones((n, n))
        dirs = np.zeros((5, n, n))
        dirs[3] = 1.0                                                      # everything flows south, uniformly
        r, mask, _ = self.feed(tr, Q, dirs, days=5)
        self.assertEqual(r["river_cells"], 0)

    def test_R4_pond_exclusive_and_dormant(self):
        tr = self.tracker()
        cells = [(6, i) for i in range(1, 9)]
        Q, dirs = self.path(cells)
        self.feed(tr, Q, dirs)
        # still pond appears over the channel: deep water, no flow -> pond immediately, never river
        h = np.zeros((12, 12))
        h[6, 1:9] = 0.3
        r, mask, pond = self.feed(tr, Q * 0, dirs * 0, h=h, days=1)
        self.assertFalse((mask & pond).any())
        self.assertEqual(r["river_cells"], 0)
        # stale channel without flow (no pond) -> dormant, not counted as flowing river
        tr = self.tracker()
        self.feed(tr, Q, dirs)
        r, mask, pond = self.feed(tr, Q * 0, dirs * 0, days=1)
        self.assertEqual(r["river_cells"], 0)
        self.assertGreater(r["dormant_channel_cells"], 0)


class TestCoupledInvariance(unittest.TestCase):
    sc = {"terrain": "valley", "climate": "moss", "composition": "all8", "seed": 11, "days": 120}

    def run_hash(self, days=120, permute_every=None, snap_every=None, **kw):
        s = Simulation(dict(self.sc, **kw))
        for d in range(days):
            if permute_every and d % permute_every == 0 and len(s.eco.pop) > 1:
                order = rng.hash32(99, 99, d, np.arange(len(s.eco.pop))).argsort()
                s.eco.pop.permute(order)
            s.step()
            if snap_every and s.day % snap_every == 0:
                s.snapshot()
        return s.state_hash(), s

    def test_seed_reproducibility(self):
        a, _ = self.run_hash()
        b, _ = self.run_hash()
        c, _ = self.run_hash(seed=12)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_update_order_invariance(self):
        a, _ = self.run_hash()
        b, _ = self.run_hash(permute_every=7)
        self.assertEqual(a, b)

    def test_observer_cadence_noninterference(self):
        a, _ = self.run_hash(days=330)
        b, _ = self.run_hash(days=330, snap_every=300)
        c, _ = self.run_hash(days=330, snap_every=37)
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_ledgers_and_finiteness_all8(self):
        s = Simulation(dict(self.sc, days=300, climate="wet"))
        worst = {"w": 0, "s": 0, "m": 0}
        for d in range(300):
            r = s.step()
            worst["w"] = max(worst["w"], abs(r["res_water_m3"]))
            worst["s"] = max(worst["s"], abs(r["res_soil_m3"]))
            worst["m"] = max(worst["m"], abs(r["res_matter_kg"]))
            self.assertLessEqual(r["max_daily_dz_m"], TC["sediment"]["max_dz_per_day_m"] + 1e-12)
        self.assertLess(worst["w"], 1e-9)
        self.assertLess(worst["s"], 1e-9)
        self.assertLess(worst["m"], 1e-9)


if __name__ == "__main__":
    unittest.main()
