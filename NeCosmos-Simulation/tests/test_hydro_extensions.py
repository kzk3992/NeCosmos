"""Tests for interflow, snow / frozen ground and the anchor-based river rule (review notes 13-14)."""
import copy
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from src.hydrology import rivers, water  # noqa: E402
from test_numerics import TC, bare_world, storage, tcfg  # noqa: E402


class TestInterflowSnow(unittest.TestCase):
    def valley(self):
        n = 16
        jj, ii = np.mgrid[0:n, 0:n]
        z = 1.0 + 0.08 * np.abs(ii - 7.5) * 0.5 + 0.02 * jj * 0.5
        return bare_world(n=n, z=z, closed=True, soil=0.3)

    def test_interflow_converges_and_conserves(self):
        w = self.valley()
        w["Ws"][:] = 0.6 * TC["soil"]["field_capacity"] * 0.3
        cfg = tcfg(hydrology__interflow_per_day=2.0)
        w0, _ = storage(w)
        for d in range(200):
            o = water.daily(w, cfg, 0.0, 0.0, erosion=False)
        w1, _ = storage(w)
        self.assertAlmostEqual(w1, w0, delta=1e-10)
        theta = w["Ws"] / (TC["soil"]["field_capacity"] * w["soil"])
        self.assertGreater(theta[:, 7:9].mean(), theta[:, [1, 14]].mean() + 0.2)   # wetter valley floor
        self.assertGreater(float(w["h"][:, 7:9].sum()), 0.0)                        # seepage to the surface

    def test_snow_frozen_melt_ledger(self):
        w = self.valley()
        cfg = tcfg()
        w0, _ = storage(w)
        tot_r = tot_e = 0.0
        w["T_air"] = np.full(w["h"].shape, -8.0)
        for d in range(60):
            o = water.daily(w, cfg, 0.004, 0.0002)
            tot_r += o["ledger"]["rain"]
            tot_e += o["ledger"]["evap_surface"] + o["ledger"]["evap_soil"]
        self.assertGreater(float(w["snow"].sum()), 0.0)
        self.assertEqual(o["ledger"]["melt"], 0.0)
        w["T_air"] = np.full(w["h"].shape, 6.0)
        melt = 0.0
        for d in range(60):
            o = water.daily(w, cfg, 0.0, 0.0)
            melt += o["ledger"]["melt"]
            tot_e += o["ledger"]["evap_surface"] + o["ledger"]["evap_soil"]
        self.assertGreater(melt, 0.0)
        self.assertLess(float(w["snow"].sum()), 1e-12)
        w1, _ = storage(w)
        self.assertAlmostEqual(w1 - w0, tot_r - tot_e, delta=1e-10)


class TestAnchorRivers(unittest.TestCase):
    def tracker(self, n=14):
        cfg = copy.deepcopy(TC)
        cfg["river"].update(persist_on_days=1, persist_off_days=3, ema_tau_days=1)
        return rivers.RiverTracker((n, n), cfg, np.zeros((n, n), bool), np.ones((n, n)))

    def feed(self, tr, Q, dirs, days=3):
        n = Q.shape[0]
        for d in range(1, days + 1):
            r, mask, pond, _ = tr.update(d, Q, dirs, np.zeros((n, n)), np.ones((n, n)), 0.25)
        return r, mask

    def test_bend_keeps_continuity(self):
        n = 14
        Q = np.zeros((n, n))
        dirs = np.zeros((5, n, n))
        path = [(10, i) for i in range(2, 7)] + [(j, 6) for j in range(9, 3, -1)]   # east, then south
        for k, (j, i) in enumerate(path):
            Q[j, i] = 0.5
            if k + 1 < len(path):
                nj, ni = path[k + 1]
                dirs[{(0, 1): 0, (0, -1): 1, (1, 0): 2, (-1, 0): 3}[(nj - j, ni - i)], j, i] = 0.5
            else:
                dirs[3, j, i] = 0.5
        Q[10, 7] = 0.45                          # bend cell has a strong lateral neighbour (not concentrated)
        r, mask = self.feed(self.tracker(), Q, dirs)
        self.assertEqual(r["river_components"], 1)
        self.assertGreaterEqual(r["river_longest"], len(path))

    def test_wide_sheet_rejected_even_with_some_anchors(self):
        n = 14
        Q = np.full((n, n), 0.5)
        Q[:, 6] = 0.9                            # one concentrated column inside a sheet
        dirs = np.zeros((5, n, n))
        dirs[3] = Q
        r, mask = self.feed(self.tracker(), Q, dirs)
        self.assertLessEqual(r["river_cells"], n)   # at most the concentrated column, never the sheet


class TestExistingRiver(unittest.TestCase):
    def test_R17_existing_river_day0_and_labels(self):
        from src.coupling.simulation import Simulation
        s = Simulation({"terrain": "initial_river", "climate": "wet", "composition": "none", "seed": 11, "days": 5,
                        "overrides": {"terrain.river.q_on_m3_day": 0.004, "terrain.river.q_off_m3_day": 0.002}})
        self.assertGreater(s.initial_water_m3, 0)
        self.assertGreaterEqual(s.river.events["preexisting_river_day0_cells"], 30)   # continuous N->S centreline
        self.assertTrue((s.river.preexisting <= s.channel_mask | s.river.preexisting).all())
        r = s.step()
        self.assertGreater(r["river_cells"], 0)                      # river exists from day 1, not emerged
        self.assertEqual(r["natural_river_cells"], 0)                # no incision yet -> not natural
        self.assertEqual(r["preexisting_river_cells"], r["river_cells"])
        self.assertLess(abs(r["res_water_m3"]), 1e-9)                 # stock counted in initial storage
        dry = Simulation({"terrain": "initial_river", "climate": "wet", "composition": "none", "seed": 11, "days": 5,
                          "initial_water": False})
        self.assertEqual(dry.initial_water_m3, 0.0)


if __name__ == "__main__":
    unittest.main()
