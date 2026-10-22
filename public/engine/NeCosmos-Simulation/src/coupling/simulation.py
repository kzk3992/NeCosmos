"""Coupled daily simulation: terrain + hydrology + sediment + rivers + 8-species ecology.

Daily order (fixed step; observers never modify state or draw random numbers):
  1 unlock schedule (staged: +1 level every 300 d)    2 weather (exogenous counter RNG, seed+climate only)
  3 hydrology + sediment (substeps)                    4 river/pond tracker
  5 ecology (synchronous allocation, counter RNG)       6 coupling: cover, compaction, cat digging,
                                                          fish resuspension, humification, slime retention,
                                                          fluff warmth, wisdom fire
  7 creep (shared |dz| budget)                          8 exfiltration, biome hysteresis, ledgers, record
Ledgers (residual = change in storage - net external flux, expected ~1e-12):
  water  (m^3): surface + soil water;  in rain + wisdom water;  out evaporation + plant use + outflow
  soil   (m^3): soil + suspended/resting sediment;  in humified organic volume;  out boundary export
  matter (kg):  N + O + R + G + cat mass;  in catnip;  out humified mass
"""
import hashlib
import json
import math
import os
import time

import numpy as np

from ..ecosystem.cats import CHIE, FUWA, GRASS, MOGU, SAKANA, SLIME, SP, TORI, Ecology
from ..hydrology import rivers, water
from ..terrain import generate, protection, soilmove
from . import rng

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BIOMES = ["moss", "desert", "wet", "cold", "aquatic"]
PHASE3_META = os.path.join(os.path.dirname(HERE), "NeCosmos-Assets", "objects", "metadata", "cat_tower_01.json")


def load_cfg():
    def j(p):
        with open(os.path.join(HERE, "configs", p), encoding="utf-8") as f:
            return json.load(f)
    return {"species": j("species/species.json"), "terrain": j("terrain/terrain.json"),
            "climates": j("scenarios/climates.json"), "comps": j("scenarios/compositions.json")}


def code_hash():
    h = hashlib.sha256()
    for base, _, names in sorted(os.walk(os.path.join(HERE, "src"))):
        for n in sorted(names):
            if n.endswith(".py"):
                h.update(open(os.path.join(base, n), "rb").read())
    return h.hexdigest()[:16]


def config_hash(cfg):
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


class Simulation:
    def __init__(self, sc, cfg=None):
        """sc keys: terrain, climate, composition, seed, days; optional: terrain_motion, cat_effects,
        rain_mult, erosion_mult, grass_breed_mult, grass_repro, grass_spawn, towers (list of (x,y,yaw)),
        unlock ('fixed'|'staged'), max_dz, substeps, overrides (dotted cfg paths)."""
        cfg = json.loads(json.dumps(cfg or load_cfg()))
        for path, val in sc.get("overrides", {}).items():
            d = cfg
            keys = path.split(".")
            for k in keys[:-1]:
                d = d[k]
            d[keys[-1]] = val
        self.cfg, self.sc = cfg, sc
        tc = cfg["terrain"]
        if "max_dz" in sc:
            tc["sediment"]["max_dz_per_day_m"] = sc["max_dz"]
        if "substeps" in sc:
            tc["hydrology"]["substeps"] = sc["substeps"]
        em = sc.get("erosion_mult", 1.0)
        tc["sediment"]["k_erode"] *= em
        self.seed = int(sc["seed"])
        self.clim = cfg["climates"]["climates"][sc["climate"]]
        self.days = int(sc["days"])
        self.motion = sc.get("terrain_motion", True)
        self.cat_effects = sc.get("cat_effects", True)
        ter = generate.build(tc, sc["terrain"], self.seed)
        n, dx = tc["grid"]["n"], tc["grid"]["cell_m"]
        A = dx * dx
        noise = generate.value_noise(n, self.seed + 77, 2)
        noise2 = generate.value_noise(n, self.seed + 91, 2)
        edge = np.zeros((n, n))
        edge[0, :] += 1
        edge[-1, :] += 1
        edge[:, 0] += 1
        edge[:, -1] += 1
        w = {"A": A, "dx": dx, "x": ter["x"], "y": ter["y"], "rim": ter["rim"], "edge_faces": edge,
             "bedrock": ter["bedrock"], "soil": ter["soil"].copy(), "h": np.zeros((n, n)), "sed": np.zeros((n, n)),
             "cover": np.full((n, n), 0.1), "hardness": np.clip(sc.get("hardness_init", 0.4) + 0.1 * noise, 0, 1),
             "retention": np.ones((n, n)), "evap_mult": np.ones((n, n)), "protection": np.zeros((n, n)), "snow": np.zeros((n, n)),
             "N": np.clip(self.clim["init_nut"] + 0.1 * noise2, 0.06, 0.95), "O": 0.12 + 0.12 * (noise + 1) / 2,
             "R": 0.03 + 0.03 * (noise + 1) / 2, "G": np.zeros((n, n)), "activity": np.zeros((n, n)),
             "fuwa_near": np.zeros((n, n), bool), "warm": np.zeros((n, n)), "biome_id": np.zeros((n, n), int),
             "biome_prog": np.zeros((n, n), int), "dz_used": np.zeros((n, n)), "max_dz": tc["sediment"]["max_dz_per_day_m"],
             "roundoff": {"soil": 0.0, "sed": 0.0, "water_h": 0.0}}
        fc = tc["soil"]["field_capacity"]
        w["Ws"] = np.clip(self.clim["init_moist"], 0, 1) * fc * w["soil"]
        w["z"] = w["bedrock"] + w["soil"]
        self.w = w
        self.z0 = w["z"].copy()
        self.zmean0 = float(w["z"].mean())
        self.channel_mask = ter["channel_mask"]
        g = tc["grid"]
        self.unlock_masks = generate.unlock_masks(n, g["unlock_levels"], g["unlock_initial_fraction"])
        self.level = 1
        self.unlock_mode = sc.get("unlock", "fixed")
        w["unlocked"] = self.unlock_masks[0].copy()
        # towers (Phase 3 metadata, read-only)
        self.towers = []
        if sc.get("towers"):
            meta = protection.load_tower(PHASE3_META)
            for (tx, ty, yaw) in sc["towers"]:
                tw = protection.place(w, {"x": tx, "y": ty, "yaw": yaw, "meta": meta})
                self.towers.append(tw)
            w["protection"] = protection.protection_field(w["x"], w["y"], self.towers, dx)
        w["z"] = w["bedrock"] + w["soil"]
        self.river = rivers.RiverTracker((n, n), tc, self.channel_mask, w["z"])
        self.initial_water_m3 = 0.0
        iw = tc["terrains"][sc["terrain"]].get("initial_water_m", 0.0) if sc.get("initial_water", True) else 0.0
        if iw > 0 and ter["centreline"]:
            # existing river at day 0: finite water stock on the centreline network + saturated soil
            # beneath (no ongoing source; counted in the initial storage of the water ledger)
            ch = self.river.initialize_existing(ter["centreline"], (n, n), 1.5 * tc["river"]["q_on_m3_day"])
            w["h"][ch] = iw
            w["Ws"][ch] = fc * w["soil"][ch]
            self.initial_water_m3 = float(iw * ch.sum() * A)
        self._env_cells(0)
        self._biome(force=True)
        comp = {k: v for k, v in cfg["comps"][sc["composition"]].items() if not k.startswith("_")} if sc["composition"] != "none" else {}
        self.eco = Ecology(cfg["species"], sc["composition"], {
            "grass_repro": sc.get("grass_repro", True), "grass_spawn": sc.get("grass_spawn", False),
            "grass_breed_mult": sc.get("grass_breed_mult", 1.0), "space_mult": sc.get("space_mult", 1.0),
            "cat_effects": self.cat_effects, "lifespan_mult": sc.get("lifespan_mult", 1.0),
            "production_mult": sc.get("production_mult", 1.0),
            **({"grass_repro_min_age": sc["grass_repro_min_age"]} if "grass_repro_min_age" in sc else {})})
        if comp:
            for k in comp:
                comp[k] = int(round(comp[k] * sc.get("init_pop_mult", 1.0)))
            self.eco.place_initial(comp, w, self.seed)
        self.day = 0
        self.cum = {"rain": 0.0, "outflow": 0.0, "evap": 0.0, "plant": 0.0, "sed_export": 0.0, "humified_kg": 0.0,
                    "catnip_kg": 0.0, "wisdom_water": 0.0}
        self.store0 = self._storages()
        self.prev_store = dict(self.store0)
        self.events = []
        self.extinct = {}
        self.tipping = []
        self._seen = np.bincount(self.eco.pop.sp, minlength=8) > 0      # species present at day 0

    # ------------------------------------------------------------------ environment
    def _season(self, day):
        s = math.sin((day % 360) / 360 * 2 * math.pi)
        return s

    def _env_cells(self, day):
        w, c = self.w, self.clim
        s = self._season(day)
        lapse = self.cfg["climates"]["lapse_C_per_m"]
        fire = np.zeros_like(w["h"])
        if hasattr(self, "eco"):
            for (fj, fi, until) in self.eco.fires:
                if until >= day:
                    jj, ii = np.mgrid[0:w["h"].shape[0], 0:w["h"].shape[1]]
                    fire = np.maximum(fire, np.where((np.hypot(jj - fj, ii - fi) <= 1.5) & (w["O"] > 0.001), 3.0, 0.0))
        w["fire"] = fire
        w["T"] = c["temp_C"] + c["season_amp_C"] * s + lapse * (w["z"] - self.zmean0) + fire + w["warm"]
        fc = self.cfg["terrain"]["soil"]["field_capacity"]
        cap = fc * w["soil"] * w["retention"]
        w["theta"] = np.clip(w["Ws"] / np.maximum(cap, 1e-9), 0, 1)
        w["moist"] = np.clip(w["theta"] + 4 * w["h"], 0, 1)
        self.light = self.cfg["climates"]["light"] * (1 + self.cfg["climates"]["light_season_amp"] * s)

    def weather(self, day):
        """Exogenous daily rain (m) and potential evaporation (m): depends only on seed, climate, day."""
        c = self.clim
        u = rng.u01(self.seed, rng.WEATHER, day, [0, 1])
        wet = u[0] < c["wet_day_prob"]
        amount = (c["rain_mm_day"] / c["wet_day_prob"]) * -math.log(max(u[1], 1e-12)) if wet else 0.0
        rain = amount * self.sc.get("rain_mult", 1.0) / 1000.0
        T = c["temp_C"] + c["season_amp_C"] * self._season(day)
        light = self.cfg["climates"]["light"] * (1 + self.cfg["climates"]["light_season_amp"] * self._season(day))
        epot = max(0.2, c["evap_base_mm"] + c["evap_mm_per_C"] * T) * light * self.sc.get("evap_mult", 1.0) / 1000.0
        return rain, epot

    # ------------------------------------------------------------------ storages / ledgers
    def _storages(self):
        w, A = self.w, self.w["A"]
        p = self.eco.pop
        return {"water": float((w["h"].sum() + w["Ws"].sum() + w["snow"].sum()) * A),
                "soil": float(w["soil"].sum() * A + w["sed"].sum()),
                "matter": float(w["N"].sum() + w["O"].sum() + w["R"].sum() + w["G"].sum() + p.mass.sum())}

    # ------------------------------------------------------------------ coupling
    def _coupling(self, day, st_eco):
        w, cfg = self.w, self.cfg
        A = w["A"]
        p = self.eco.pop
        n0, n1 = w["h"].shape
        out = {"dig_m3": 0.0, "resuspend_m3": 0.0, "humified_kg": 0.0, "humified_m3": 0.0, "cover_added": 0.0,
               "litter_kg": 0.0, "abiotic_min_kg": 0.0, "n_diffused_kg": 0.0,
               "cover_worn": 0.0, "compaction": 0.0, "retention_cells": 0, "warm_cells": 0}
        cnt = lambda mask: np.bincount((p.j * n1 + p.i)[mask], minlength=n0 * n1).reshape(n0, n1)
        trample = np.bincount(p.j * n1 + p.i, self.eco.trample[p.sp] if len(p) else np.zeros(0), n0 * n1).reshape(n0, n1)
        w["activity"] = 0.95 * w["activity"] + 0.05 * trample          # activity history (diagnostic, always)
        if self.cat_effects:
            grass_cnt = cnt(p.sp == GRASS)
            before = w["cover"].copy()
            w["cover"] = np.clip(w["cover"] * 0.992 + 0.038 * grass_cnt, 0, 1)      # [confirmed]
            out["cover_added"] = float(np.maximum(w["cover"] - before * 0.992, 0).sum())
            p.infl_cover = np.where(p.sp == GRASS, 0.038, 0.0)
            # direct soil disturbance: compaction / cover wear [provisional]
            hb = w["hardness"].copy()
            w["hardness"] = np.clip(w["hardness"] + 0.002 * w["activity"] * (1 - w["hardness"]) * (1 - w["protection"])
                                    - 0.001 * (w["hardness"] - self.sc.get("hardness_init", 0.4)), 0, 1)
            out["compaction"] = float(np.maximum(w["hardness"] - hb, 0).sum())
            cb = w["cover"].copy()
            w["cover"] = np.clip(w["cover"] - 0.004 * w["activity"], 0, 1)
            out["cover_worn"] = float((cb - w["cover"]).sum())
            if self.motion:
                # mogumogu digging: soil pushed to the 4 neighbours (conserved, shared budget)
                dig = cnt(p.sp == MOGU) * self.eco.S["mogumogu"]["dig"][0]
                qx = np.zeros((n0, n1 - 1))
                qy = np.zeros((n0 - 1, n1))
                qx += dig[:, 1:] / 4          # from i+1 to i
                qx -= dig[:, :-1] / 4         # from i to i+1
                qy += dig[1:, :] / 4
                qy -= dig[:-1, :] / 4
                out["dig_m3"] = soilmove.transfer_faces(w, qx, qy, frozen=w["rim"])
                nm = max(int((p.sp == MOGU).sum()), 1)
                p.infl_soil_m3 = np.where(p.sp == MOGU, out["dig_m3"] / nm, p.infl_soil_m3)
                # fish resuspension: soil -> suspended sediment where fish swim in water
                fish = cnt((p.sp == SAKANA)) * (w["h"] > 0.02)
                v = soilmove.local_exchange(w, fish * self.eco.S["sakana"]["resuspend"][0] * (1 - w["protection"]) * (~w["rim"]), +1)
                out["resuspend_m3"] = float(v.sum())
                fishes = (p.sp == SAKANA) & (w["h"][p.j, p.i] > 0.02)
                nf = max(int(fishes.sum()), 1)
                p.infl_soil_m3 = np.where(fishes, out["resuspend_m3"] / nf, p.infl_soil_m3)
            # slime retention / evaporation [provisional]; fluff warmth [provisional]
            sl = cnt(p.sp == SLIME) > 0
            w["retention"] = np.where(sl, self.eco.S["slime"]["retention_capacity_mult"][0], 1.0)
            w["evap_mult"] = np.where(sl, self.eco.S["slime"]["evap_mult"][0], 1.0)
            fu = cnt(p.sp == FUWA)
            near = fu.copy()
            near[1:, :] += fu[:-1, :]
            near[:-1, :] += fu[1:, :]
            near[:, 1:] += fu[:, :-1]
            near[:, :-1] += fu[:, 1:]
            w["fuwa_near"] = near >= 2
            w["warm"] = np.where((fu > 0) & (near >= 2), self.eco.S["fuwa"]["cluster_warmth_C"][0], 0.0)
            out["retention_cells"] = int(sl.sum())
            out["warm_cells"] = int((w["warm"] > 0).sum())
        else:
            # cat_effects OFF: cover is frozen (no addition, no decay, no wear), hardness unchanged,
            # no digging / resuspension / transport / retention / warmth. Intrinsic ecology (uptake,
            # grazing, decomposition, excretion, carcasses) continues.
            w["retention"][:] = 1.0
            w["evap_mult"][:] = 1.0
            w["warm"][:] = 0.0
            fu = cnt(p.sp == FUWA)
            near = fu.copy()
            near[1:, :] += fu[:-1, :]
            near[:-1, :] += fu[1:, :]
            near[:, 1:] += fu[:, :-1]
            near[:, :-1] += fu[:, 1:]
            w["fuwa_near"] = near >= 2
        # abiotic soil biogeochemistry [provisional; always on, independent of cats]:
        # litter decay G -> O, slow mineralization O -> N, nutrient diffusion in soil water (conserved)
        bg = self.cfg["terrain"]["soil_biogeochem"]
        lit = w["G"] * bg["litter_decay_per_day"]
        w["G"] -= lit
        w["O"] += lit
        mn = w["O"] * bg["abiotic_mineralization_per_day"]
        w["O"] -= mn
        w["N"] += mn
        out["litter_kg"], out["abiotic_min_kg"] = float(lit.sum()), float(mn.sum())
        D = bg["nutrient_diffusion_per_day"]
        if D > 0:
            th = w["theta"]
            qx = D * (w["N"][:, 1:] - w["N"][:, :-1]) * np.minimum(th[:, 1:], th[:, :-1])    # >0: i+1 -> i
            qy = D * (w["N"][1:, :] - w["N"][:-1, :]) * np.minimum(th[1:, :], th[:-1, :])
            outN = np.zeros_like(w["N"])
            outN[:, 1:] += np.maximum(qx, 0)
            outN[:, :-1] += np.maximum(-qx, 0)
            outN[1:, :] += np.maximum(qy, 0)
            outN[:-1, :] += np.maximum(-qy, 0)
            sc = np.where(outN > w["N"], w["N"] / np.maximum(outN, 1e-300), 1.0)
            qx = np.where(qx > 0, qx * sc[:, 1:], qx * sc[:, :-1])
            qy = np.where(qy > 0, qy * sc[1:, :], qy * sc[:-1, :])
            dN = np.zeros_like(w["N"])
            dN[:, :-1] += qx
            dN[:, 1:] -= qx
            dN[:-1, :] += qy
            dN[1:, :] -= qy
            w["N"] = w["N"] + dN
            out["n_diffused_kg"] = float(np.abs(qx).sum() + np.abs(qy).sum())
        # wisdom fire burns organic -> N .65, R .35 [confirmed]
        if (w["fire"] > 0).any():
            burned = np.minimum(w["O"], 0.0015) * (w["fire"] > 0)
            w["O"] -= burned
            w["N"] += burned * 0.65
            w["R"] += burned * 0.35
        # humification: slow organic -> soil volume (mass leaves matter ledger), shared budget
        if self.motion:
            so = self.cfg["terrain"]["soil"]
            want = w["R"] * so["humify_rate_per_day"]
            vol = want / so["dry_density_kg_m3"]
            ok = np.minimum(vol, soilmove.remaining(w)) * (~w["rim"])
            mass = ok * so["dry_density_kg_m3"]
            w["R"] -= mass
            w["soil"] += ok / A
            w["dz_used"] += ok / A
            out["humified_kg"] = float(mass.sum())
            out["humified_m3"] = float(ok.sum())
        return out

    def _biome(self, force=False):
        w = self.w
        T, m, org = w["T"], w["moist"], w["O"] + w["R"]
        want = np.where((T < 9) & (m < 0.69), 3, np.where(m < 0.30, 1, np.where((m > 0.69) & (org > 0.13), 2,
                        np.where(T < 6, 3, 0))))                                       # [confirmed] tileBiome
        want = np.where(w["h"] >= 0.05, 4, want)                                         # [provisional] aquatic
        if force:
            w["biome_id"] = want
            return
        diff = want != w["biome_id"]
        w["biome_prog"] = np.where(diff, w["biome_prog"] + 1, 0)
        flip = w["biome_prog"] > 12                                                       # [confirmed] 12-day hysteresis
        w["biome_id"] = np.where(flip, want, w["biome_id"])
        w["biome_prog"] = np.where(flip, 0, w["biome_prog"])

    # ------------------------------------------------------------------ one day
    def step(self):
        self.day += 1
        day, w, cfg = self.day, self.w, self.cfg
        A = w["A"]
        if self.unlock_mode == "staged" and day % cfg["terrain"]["grid"]["unlock_interval_days"] == 0 and self.level < len(self.unlock_masks):
            self.level += 1
            w["unlocked"] = self.unlock_masks[self.level - 1].copy()
            self.events.append((day, f"unlock level {self.level}"))
        w["dz_used"] = np.zeros_like(w["h"])
        z_start = (w["bedrock"] + w["soil"]).copy()
        rain, epot = self.weather(day)
        self._env_cells(day)                      # air temperature for snow / frozen ground
        w["T_air"] = w["T"]
        hyd = water.daily(w, cfg["terrain"], rain, epot, erosion=self.motion)
        w["z"] = w["bedrock"] + w["soil"]
        riv, river_mask, pond_mask, down = self.river.update(day, hyd["Q"], hyd["dirs"], w["h"], w["z"], A)
        self.river_mask, self.pond_mask = river_mask, pond_mask
        self._env_cells(day)
        st = self.eco.step(w, day, self.seed, {"light": self.light})
        coup = self._coupling(day, st)
        creep_m3 = water.creep(w, cfg["terrain"]) if self.motion else 0.0
        ex = soilmove.exfiltrate(w, cfg["terrain"]["soil"]["field_capacity"])     # retention may have dropped
        w["z"] = w["bedrock"] + w["soil"]
        self._env_cells(day)
        self._biome()
        dz_day = np.abs(w["z"] - z_start)
        # ledgers
        led = hyd["ledger"]
        store = self._storages()
        ext_w = led["rain"] + st["wisdom_water_m3"] - led["evap_surface"] - led["evap_soil"] - st["plant_use_m3"] - led["outflow"]
        ext_s = coup["humified_m3"] - led["sed_export"]
        ext_m = st["catnip_in_kg"] - coup["humified_kg"]
        res = {k: store[k] - self.prev_store[k] - e for k, e in (("water", ext_w), ("soil", ext_s), ("matter", ext_m))}
        self.prev_store = store
        for k, v in (("rain", led["rain"]), ("outflow", led["outflow"]), ("evap", led["evap_surface"] + led["evap_soil"]),
                     ("plant", st["plant_use_m3"]), ("sed_export", led["sed_export"]), ("humified_kg", coup["humified_kg"]),
                     ("catnip_kg", st["catnip_in_kg"]), ("wisdom_water", st["wisdom_water_m3"])):
            self.cum[k] += v
        p = self.eco.pop
        counts = np.bincount(p.sp, minlength=8)
        # births/spawns today may add species; extinction = seen before and zero now
        self._seen |= (counts > 0) | (st["births_by_sp"] > 0) | (st["deaths_by_sp"] > 0)
        for s_i, name in enumerate(SP):
            if counts[s_i] == 0 and name not in self.extinct and self._had(s_i):
                self.extinct[name] = day
                self.tipping.append((day, f"extinct:{name}"))
        biome_area = np.bincount(w["biome_id"].ravel(), minlength=5) * A
        n0, n1 = w["h"].shape
        row = {"day": day, "pop_total": int(len(p))}
        row.update({f"pop_{s}": int(counts[k]) for k, s in enumerate(SP)})
        row.update({"births": st["births"], "deaths_starvation": st["deaths_starvation"], "deaths_stress": st["deaths_stress"],
                    "deaths_old": st["deaths_old"], "deaths_collapse": st["deaths_collapse"], "spawned_grass": st["spawned"],
                    "res_G_kg": float(w["G"].sum()), "res_N_kg": float(w["N"].sum()), "res_O_kg": float(w["O"].sum()),
                    "res_R_kg": float(w["R"].sum()), "cat_mass_kg": float(p.mass.sum()), "production_kg": st["production"],
                    "grazed_kg": st["grazed"], "decomposed_kg": st["decomposed"],
                    "water_surface_m3": float(w["h"].sum() * A), "water_soil_m3": float(w["Ws"].sum() * A),
                    "snow_m3": float(w["snow"].sum() * A), "snowfall_m3": led["snowfall"], "melt_m3": led["melt"],
                    "interflow_m3": led["interflow"],
                    "rain_m3": led["rain"], "evap_surface_m3": led["evap_surface"], "evap_soil_m3": led["evap_soil"],
                    "plant_use_m3": st["plant_use_m3"], "outflow_m3": led["outflow"], "infil_m3": led["infil"],
                    "exfil_m3": led["exfil"] + ex, "wisdom_water_m3": st["wisdom_water_m3"],
                    "soil_m3": float(w["soil"].sum() * A), "sediment_m3": float(w["sed"].sum()),
                    "sed_export_m3": led["sed_export"], "eroded_m3": led["eroded"], "deposited_m3": led["deposited"],
                    "throttled_m3": led["throttled"], "creep_m3": creep_m3, "dig_m3": coup["dig_m3"], "resuspend_m3": coup["resuspend_m3"],
                    "humified_kg": coup["humified_kg"], "max_height_m": float(w["z"].max()), "mean_height_m": float(w["z"].mean()),
                    "max_daily_dz_m": float(dz_day.max()), "max_dz_used_m": float(w["dz_used"].max()),
                    "wet_cells": int((w["h"] > cfg["terrain"]["hydrology"]["wet_depth_m"]).sum())})
        row.update(riv)
        row.update({f"biome_{b}_m2": float(biome_area[k]) for k, b in enumerate(BIOMES)})
        row["protection_area_m2"] = float((w["protection"] > 0.05).sum() * A)
        if self.towers:
            sts = [protection.status(w, tw) for tw in self.towers]
            row["tower_ground_err_m"] = max(s["ground_error_m"] for s in sts)
            row["tower_flood_depth_m"] = max(s["flood_depth_m"] for s in sts)
            row["towers_flooded"] = sum(s["flooded"] for s in sts)
            self.tower_status = sts
        else:
            row["tower_ground_err_m"] = row["tower_flood_depth_m"] = 0.0
            row["towers_flooded"] = 0
        for k, name in enumerate(SP):                       # executed actions / effects per species
            row[f"moves_{name}"] = int(st["sp_moved"][k])
            row[f"produced_kg_{name}"] = float(st["sp_produced"][k])
            row[f"grazed_kg_{name}"] = float(st["sp_grazed"][k])
            row[f"decomposed_kg_{name}"] = float(st["sp_decomposed"][k])
            row[f"transport_kg_{name}"] = float(st["sp_transport_kg"][k])
        row.update({"litter_kg": coup["litter_kg"], "abiotic_min_kg": coup["abiotic_min_kg"], "n_diffused_kg": coup["n_diffused_kg"]})
        row["moist_mean_unlocked"] = float(w["moist"][w["unlocked"]].mean())
        row["theta_mean_unlocked"] = float(w["theta"][w["unlocked"]].mean())
        row.update({"fx_cover_added_grass": coup["cover_added"], "fx_cover_worn": coup["cover_worn"],
                    "fx_compaction": coup["compaction"], "fx_dig_m3_mogumogu": coup["dig_m3"],
                    "fx_resuspend_m3_sakana": coup["resuspend_m3"], "fx_retention_cells_slime": coup["retention_cells"],
                    "fx_warm_cells_fuwa": coup["warm_cells"]})
        self.transport_events_today = st["transport_events"]
        row.update({"res_water_m3": res["water"], "res_soil_m3": res["soil"], "res_matter_kg": res["matter"],
                    "unlock_level": self.level, "unlocked_m2": float(w["unlocked"].sum() * A),
                    "catnip_active": int(day <= self.eco.catnip_until), "fire_active": int((w["fire"] > 0).any()),
                    "wisdom_event": st["wisdom_event"], "roundoff_total": sum(w["roundoff"].values())})
        for k in ("births_by_sp", "deaths_by_sp"):
            for s_i, name in enumerate(SP):
                row[f"{k[:-6]}_{name}"] = int(st[k][s_i])
        self._check_finite(row)
        return row

    def _had(self, s_i):
        return bool(self._seen[s_i])

    def _check_finite(self, row):
        w = self.w
        for k in ("h", "Ws", "soil", "sed", "N", "O", "R", "G"):
            a = w[k]
            if not np.isfinite(a).all():
                raise FloatingPointError(f"non-finite {k} on day {self.day}")
            if a.min() < -1e-9:
                raise FloatingPointError(f"negative {k} ({a.min()}) on day {self.day}")
        if len(self.eco.pop) and (not np.isfinite(self.eco.pop.energy).all() or self.eco.pop.mass.min() < -1e-9):
            raise FloatingPointError(f"bad cat state on day {self.day}")

    # ------------------------------------------------------------------ observers (read-only)
    def snapshot(self):
        w = self.w
        keys = ("bedrock", "soil", "h", "Ws", "snow", "sed", "cover", "hardness", "N", "O", "R", "G", "activity",
                "biome_id", "biome_prog", "protection", "unlocked", "T", "theta", "moist", "retention", "evap_mult",
                "fuwa_near", "warm", "dz_used")
        # Observers preserve numerical precision and the directed graph for independent audits.
        d = {k: np.array(w[k], copy=True) for k in keys}
        d["z"] = (w["bedrock"] + w["soil"]).copy()
        d["z0"] = self.z0.copy()
        d["river"] = self.river_mask.copy() if hasattr(self, "river_mask") else getattr(self.river, "preexisting", np.zeros_like(w["h"], bool)).copy()
        d["pond"] = self.pond_mask.copy() if hasattr(self, "pond_mask") else np.zeros_like(w["h"], bool)
        d["Qema"] = self.river.Qema.copy()
        d["river_dir_ema"] = self.river.dirEma.copy()
        d["river_downstream"] = self.river.prev_down.copy() if self.river.prev_down is not None else np.argmax(self.river.dirEma, axis=0)
        d["river_on_count"] = self.river.on_count.copy()
        d["river_off_count"] = self.river.off_count.copy()
        d["river_hysteresis_flag"] = self.river.river.copy()
        d["channel_mask"] = self.channel_mask.copy()
        for k, v in self.eco.pop.to_dict().items():
            if k != "next_id":
                d["cat_" + k] = v
        return d

    def state_hash(self):
        h = hashlib.sha256()
        w = self.w
        for k in ("bedrock", "soil", "h", "Ws", "snow", "sed", "N", "O", "R", "G", "cover", "hardness"):
            h.update(np.ascontiguousarray(w[k]).tobytes())
        p = self.eco.pop
        order = np.argsort(p.id)
        for f in p.FIELDS:
            h.update(np.ascontiguousarray(getattr(p, f)[order]).tobytes())
        return h.hexdigest()


def diversity(counts):
    c = np.asarray([x for x in counts if x > 0], float)
    if c.sum() == 0:
        return 0, 0.0
    q = c / c.sum()
    return int(len(c)), float(-(q * np.log(q)).sum())
