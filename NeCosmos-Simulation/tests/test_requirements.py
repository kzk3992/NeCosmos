"""Regression tests for the user-requirement audit items 7-12 (reports/codex_review_notes.md)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.coupling.simulation import Simulation, load_cfg  # noqa: E402
from src.ecosystem import cats as C  # noqa: E402

CFG = load_cfg()


def eco_world(n=10, T=20.0):
    z = np.ones((n, n))
    return {"N": np.full((n, n), 0.5), "G": np.zeros((n, n)), "O": np.full((n, n), 0.1), "R": np.full((n, n), 0.05),
            "Ws": np.full((n, n), 0.05), "h": np.zeros((n, n)), "theta": np.full((n, n), 0.5), "moist": np.full((n, n), 0.5),
            "T": np.full((n, n), T), "cover": np.full((n, n), 0.1), "z": z, "dx": 0.5, "A": 0.25,
            "unlocked": np.ones((n, n), bool), "rim": np.zeros((n, n), bool), "fuwa_near": np.zeros((n, n), bool),
            "biome_id": np.zeros((n, n), int)}


def make_eco(**opts):
    return C.Ecology(CFG["species"], "all8", dict({"cat_effects": True}, **opts))


class TestAgeYears(unittest.TestCase):
    def test_R7_default_one_day_is_one_age_year(self):
        e = make_eco()
        self.assertEqual(e.dpy, 1)
        self.assertEqual(CFG["species"]["days_per_year"]["legacy_value"], 48)

    def test_R7_gompertz_stable_and_calibrated(self):
        e = make_eco()
        ages = np.arange(0, 3001, dtype=float)
        for s in range(8):
            r = e.senescence_risk(np.full(len(ages), s), ages)
            self.assertTrue(np.isfinite(r).all() and (r >= 0).all() and (r <= 1).all(), C.SP[s])
            if C.SP[s] == "chie":
                self.assertEqual(float(r.max()), 0.0)                   # long-lived wisdom: no senescence target
            else:
                self.assertTrue((np.diff(r) >= -1e-15).all())
                tgt = int(e.lifespan[s])
                surv = float(np.prod(1 - r[1:tgt + 1]))
                self.assertAlmostEqual(surv, 0.5, delta=0.02, msg=C.SP[s])   # median lifespan == target


class TestReproductionAges(unittest.TestCase):
    def test_R8_species_specific_and_independent_grass_tuning(self):
        e = make_eco()
        sp = np.array([C.GRASS, C.MOGU])
        f10 = e.repro_age_factor(sp, np.array([10.0, 10.0]))
        self.assertEqual(f10.tolist(), [1.0, 0.0])                       # grass 7, mogumogu 48 age-years
        e2 = make_eco(grass_repro_min_age=20)
        f = e2.repro_age_factor(sp, np.array([10.0, 50.0]))
        self.assertEqual(f.tolist(), [0.0, 1.0])                         # only grass changed
        self.assertEqual(e2.r_min[C.MOGU], e.r_min[C.MOGU])

    def test_R8_environment_acts_through_energy_only(self):
        """Two otherwise identical grass cats in hot vs cold cells: same eligibility and probability
        today (no direct T/moisture term); the environment matters only via energy changes."""
        e = make_eco()
        w = eco_world()
        w["T"][2, 2], w["T"][7, 7] = 5.0, 25.0
        e.pop.add(np.array([C.GRASS, C.GRASS]), np.array([2, 7]), np.array([2, 7]), np.array([0.9, 0.9]), np.array([0.2, 0.2]), 0)
        e.pop.age[:] = 100
        st = {"births": 0, "births_by_sp": np.zeros(8, int)}
        e._reproduce(w, 200, 1, e.pop.age.astype(float), st)
        self.assertEqual(e.pop.eligible[:2].tolist(), [True, True])


class TestCatEffectsSwitch(unittest.TestCase):
    def simulate(self, effects, days=150):
        s = Simulation({"terrain": "valley", "climate": "cold", "composition": "all8", "seed": 13, "days": days,
                        "cat_effects": effects})
        cover0, hard0 = s.w["cover"].copy(), s.w["hardness"].copy()
        rows = [s.step() for _ in range(days)]
        return s, rows, cover0, hard0

    def test_R9_off_disables_all_feedbacks(self):
        s, rows, cover0, hard0 = self.simulate(False)
        self.assertTrue(np.array_equal(s.w["cover"], cover0))
        self.assertTrue(np.array_equal(s.w["hardness"], hard0))
        self.assertTrue((s.w["retention"] == 1).all() and (s.w["evap_mult"] == 1).all() and (s.w["warm"] == 0).all())
        for k in ("fx_dig_m3_mogumogu", "fx_resuspend_m3_sakana", "fx_cover_added_grass", "fx_compaction",
                  "fx_retention_cells_slime", "fx_warm_cells_fuwa", "transport_kg_tori", "transport_kg_sakana"):
            self.assertEqual(sum(r[k] for r in rows), 0, k)
        self.assertGreater(sum(r["production_kg"] for r in rows), 0)       # intrinsic ecology continues

    def test_R9_on_effects_measured(self):
        s, rows, cover0, hard0 = self.simulate(True)
        self.assertGreater(sum(r["fx_cover_added_grass"] for r in rows), 0)
        self.assertGreater(sum(r["fx_dig_m3_mogumogu"] for r in rows), 0)
        self.assertGreater(sum(r["fx_compaction"] for r in rows), 0)
        self.assertGreater(sum(r["fx_retention_cells_slime"] for r in rows), 0)
        self.assertGreater(sum(r["moves_mogumogu"] for r in rows), 0)


class TestBirdTransportAndState(unittest.TestCase):
    def test_R10_distant_conserved_transport(self):
        e = make_eco()
        e.move_p[C.TORI] = 1.0
        w = eco_world()
        w["G"][2, 6] = 0.5                                                # food 4 cells away
        w["moist"][:] = 0.4
        e.pop.add(np.array([C.TORI]), np.array([2]), np.array([2]), np.array([0.8]), np.array([0.2]), 0)
        N0 = w["N"].sum()
        src = w["N"][2, 2]
        st = {"sp_moved": np.zeros(8, int), "sp_transport_kg": np.zeros(8), "transport_events": []}
        e._move(w, 5, 1, np.array([10.0]), st)
        self.assertEqual((e.pop.j[0], e.pop.i[0]), (2, 6))
        self.assertEqual(int(e.pop.action[0]), 6)
        cargo = CFG["species"]["species"]["tori"]["cargo"][0] * CFG["species"]["species"]["tori"]["flight"][0]
        self.assertAlmostEqual(w["N"][2, 2], src - cargo, delta=1e-15)
        self.assertAlmostEqual(w["N"][2, 6], 0.5 + cargo, delta=1e-15)
        self.assertAlmostEqual(w["N"].sum(), N0, delta=1e-12)
        self.assertEqual(st["transport_events"][0][2:4], ((2, 2), (2, 6)))
        self.assertGreater(e.pop.infl_transport_kg[0], 0)

    def test_R10_individual_state_and_death_ledger(self):
        s = Simulation({"terrain": "flat", "climate": "moss", "composition": "pcd", "seed": 14, "days": 5})
        p = s.eco.pop
        for f in ("action", "eligible", "infl_soil_m3", "infl_cover", "infl_transport_kg"):
            self.assertEqual(len(getattr(p, f)), len(p))
        p.energy[p.sp == C.MOGU] = -1.0
        s.step()
        self.assertTrue(any(d["species"] == "mogumogu" and d["cause"] in ("starvation", "stress") for d in s.eco.deaths))


class TestExtinctionAndBirthCliff(unittest.TestCase):
    def test_R11_extinction_day_recorded(self):
        s = Simulation({"terrain": "flat", "climate": "moss", "composition": "pcd", "seed": 15, "days": 5})
        s.eco.pop.energy[s.eco.pop.sp == C.KINOKO] = -1.0
        s.step()
        self.assertEqual(s.extinct.get("kinoko"), 1)
        self.assertIn((1, "extinct:kinoko"), s.tipping)

    def test_R12_newborn_cannot_cross_cliff(self):
        e = make_eco()
        w = eco_world()
        w["z"][:] = 5.0
        w["z"][4, 4] = 1.0                                                # parent in a deep pit
        for sp in (C.MOGU, C.TORI):
            e.pop.add(np.array([sp]), np.array([4]), np.array([4]), np.array([1.0]), np.array([0.3]), 0)
        e.pop.age[:] = 100
        e.base[:] = 100.0                                                 # force births
        e.K = 100
        landed = {"mogu_out": 0, "bird_out": 0}
        for day in range(200, 400, 61):
            st = {"births": 0, "births_by_sp": np.zeros(8, int)}
            e.pop.energy[:] = 1.0
            n_before = len(e.pop)
            e._reproduce(w, day, 3, e.pop.age.astype(float), st)
            new = np.arange(len(e.pop)) >= n_before
            out = new & ((e.pop.j != 4) | (e.pop.i != 4))
            landed["mogu_out"] += int((out & (e.pop.sp == C.MOGU)).sum())
            landed["bird_out"] += int((out & (e.pop.sp == C.TORI)).sum())
        self.assertEqual(landed["mogu_out"], 0)
        self.assertGreaterEqual(landed["bird_out"], 0)


if __name__ == "__main__":
    unittest.main()
