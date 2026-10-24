"""Individual-based cat ecosystem (structure of arrays, synchronous daily update).

Species index: 0 grass(草ねこ) 1 mogumogu 2 kinoko 3 fuwa 4 chie(知恵) 5 tori(鳥) 6 sakana(魚) 7 slime.
Matter unit: kg dry mass per cell (provisional scale: 1 game unit = 1 kg). Energy: game units.

Daily order (all decisions read the start-of-day state; draws are counter-based per id):
  age/senescence -> utility/FSM movement -> stress -> production & feeding (per-cell proportional allocation of N, Ws, G,
  O, R so array order never matters) -> energy costs -> excretion -> reproduction
  (occupancy from before births) -> deaths (carcass -> O) -> spontaneous grass -> wisdom clock.
Formulas marked [confirmed] come from public/index.html V0.9; [provisional] are Phase 4 choices.
"""
import math

import numpy as np

from ..coupling import rng

SP = ["grass", "mogumogu", "kinoko", "fuwa", "chie", "tori", "sakana", "slime"]
GRASS, MOGU, KINOKO, FUWA, CHIE, TORI, SAKANA, SLIME = range(8)
NB = np.array([[0, 0], [0, 1], [0, -1], [1, 0], [-1, 0]])    # stay, E, W, N, S  (dj, di)


def _v(x):
    return x[0] if isinstance(x, list) else x


def _credit(w, pool, indices, amount):
    """New weather pipeline: receipts become available only in the cycle phase."""
    target=w.get('_ecology_pending', {}).get(pool,w[pool])
    np.add.at(target,indices,amount)


class Population:
    FIELDS = ("id", "sp", "j", "i", "age", "energy", "mass", "last_birth", "born", "stress",
              "action", "eligible", "infl_soil_m3", "infl_cover", "infl_transport_kg")
    # action codes: 0 idle 1 move 2 produce 3 graze 4 decompose 5 give-birth 6 flight-transport
    # (alive individuals live in the arrays; dead ones are moved to Ecology.deaths, the death ledger)

    def __init__(self):
        self.id = np.zeros(0, np.int64)
        self.sp = np.zeros(0, np.int64)
        self.j = np.zeros(0, np.int64)
        self.i = np.zeros(0, np.int64)
        self.age = np.zeros(0, np.int64)
        self.energy = np.zeros(0)
        self.mass = np.zeros(0)
        self.last_birth = np.zeros(0, np.int64)
        self.born = np.zeros(0, np.int64)
        self.stress = np.zeros(0)
        self.action = np.zeros(0, np.int64)
        self.eligible = np.zeros(0, bool)
        self.infl_soil_m3 = np.zeros(0)
        self.infl_cover = np.zeros(0)
        self.infl_transport_kg = np.zeros(0)
        self.next_id = 1
        self.birth_records = []

    def __len__(self):
        return len(self.id)

    def add(self, sp, j, i, energy, mass, day):
        k = len(sp)
        ids = np.arange(self.next_id, self.next_id + k, dtype=np.int64)
        self.next_id += k
        cat = lambda a, b, dt=None: np.concatenate([a, np.asarray(b, dtype=a.dtype if dt is None else dt)])
        if not hasattr(self, 'birth_records'): self.birth_records = []
        self.birth_records.extend({'id': int(cid), 'species': SP[int(sp[k])], 'day': int(day),
                                   'j': int(j[k]), 'i': int(i[k])} for k,cid in enumerate(ids))
        self.id = cat(self.id, ids)
        self.sp = cat(self.sp, sp)
        self.j = cat(self.j, j)
        self.i = cat(self.i, i)
        self.age = cat(self.age, np.zeros(k))
        self.energy = cat(self.energy, energy)
        self.mass = cat(self.mass, mass)
        self.last_birth = cat(self.last_birth, np.full(k, -10**6))
        self.born = cat(self.born, np.full(k, day))
        self.stress = cat(self.stress, np.zeros(k))
        self.action = cat(self.action, np.zeros(k))
        self.eligible = cat(self.eligible, np.zeros(k, bool))
        self.infl_soil_m3 = cat(self.infl_soil_m3, np.zeros(k))
        self.infl_cover = cat(self.infl_cover, np.zeros(k))
        self.infl_transport_kg = cat(self.infl_transport_kg, np.zeros(k))
        return ids

    def keep(self, mask):
        for f in self.FIELDS:
            setattr(self, f, getattr(self, f)[mask])

    def permute(self, order):
        for f in self.FIELDS:
            setattr(self, f, getattr(self, f)[order])

    def to_dict(self):
        return {f: getattr(self, f).copy() for f in self.FIELDS} | {"next_id": self.next_id}


class Ecology:
    def __init__(self, spc, comp_name, opts):
        self.cfg = spc
        self.S = spc["species"]
        self.dpy = _v(spc["days_per_year"]["value"])
        rp = spc["reproduction"]
        self.e_thr = rp["energy_threshold"]["value"]
        self.e_cost = rp["energy_cost"]["value"]
        arr = lambda key, default: np.array([_v(self.S[s].get(key, [default])) for s in SP], float)
        self.r_min = arr("repro_min_age_years", 10 ** 9)
        self.r_min[GRASS] = opts.get("grass_repro_min_age", self.r_min[GRASS])
        self.r_start = arr("repro_decline_start_years", 10 ** 9)
        self.r_span = arr("repro_decline_span_years", 1)
        self.cooldown = arr("repro_cooldown_days", 60)
        st_ = [_v(self.S[s].get("life_stage_years", [[48, 336, 528]])) for s in SP]
        self.stage = np.array(st_, float)
        self.flight = int(_v(self.S["tori"]["flight_range_cells"]))
        self.effects = opts.get("cat_effects", True)
        self.deaths = []
        self.rate_mult = rp["rate_multiplier"]["value"]
        self.newborn_max = rp["newborn_mass_max"]["value"]
        self.K = rp["space_capacity_per_cell"]["value"] * opts.get("space_mult", 1.0)
        self.beta = spc["senescence"]["gompertz_beta_per_year"]["value"]
        self.walk = spc["movement"]["walk_slope_max"]["value"]
        self.wade = spc["movement"]["wade_depth_m"]["value"]
        self.comp = comp_name
        self.opts = opts
        g = self.S["grass"]
        self.grass_repro = opts.get("grass_repro", _v(g["reproduction_enabled"]))
        self.grass_spawn = opts.get("grass_spawn", _v(g["spontaneous_generation"]))
        self.chie_enabled = comp_name in _v(self.S["chie"]["enabled_in"])
        self.lifespan = np.array([_v(self.S[s]["lifespan_days"]) if "lifespan_days" in self.S[s] else 0 for s in SP], float)
        self.lifespan *= opts.get("lifespan_mult", 1.0)
        self.cost = np.array([_v(self.S[s].get("daily_cost", [0])) for s in SP], float)
        self.base = np.array([_v(self.S[s].get("repro_base", [0])) for s in SP], float)
        self.base[GRASS] *= opts.get("grass_breed_mult", 1.0)
        self.move_p = np.array([_v(self.S[s].get("move_prob", [0.0])) for s in SP], float)
        self.init_e = np.array([_v(self.S[s].get("init_energy", [1.2])) for s in SP], float)
        self.init_e[CHIE] = 1.2
        self.dmg_mult = np.array([1, 1, 1, 1, 1, 0.6, 0.65, 0.65])
        self.trample = np.array([0.2, _v(self.S["mogumogu"]["trample"]), 1, 1, 1, 0.3, 0.5, 0.6])
        self.pop = Population()
        self.catnip_until = -1
        self.catnip_charges = 1
        self.fires = []                 # (j, i, until)
        self.water_plan = None          # (mask, depth) for today
        self.stats = {}

    # ------------------------------------------------------------------ helpers
    def age_factor_energy(self, sp, years):
        """[confirmed shape] kitten / senior 1.12, mature .96; stage ages per species (age-years)."""
        st = self.stage[sp]
        return np.where((years < st[:, 0]) | (years >= st[:, 2]), 1.12, np.where(years >= st[:, 1], 0.96, 1.0))

    def repro_age_factor(self, sp, years):
        """Per-species: 0 before repro_min_age, 1 until decline_start, then linear decline (floor .08)."""
        return np.where(years < self.r_min[sp], 0.0, np.where(years < self.r_start[sp], 1.0,
                        np.maximum(0.08, 1 - (years - self.r_start[sp]) / self.r_span[sp])))

    def senescence_risk(self, sp, years):
        """Gompertz daily death probability evaluated in log space (no overflow at any age):
        h(a) = h0 exp(beta a), h0 = ln2 beta / (expm1(beta T)) so that P(survive to T) = 1/2."""
        tgt = np.maximum(self.lifespan[sp], 1.0)
        b = self.beta
        x = b * tgt
        log_expm1 = x + np.log1p(-np.exp(-x))
        log_h = math.log(0.693147 * b) - log_expm1 + b * years
        r = -np.expm1(-np.exp(np.minimum(log_h, 700.0)))
        return np.where(self.lifespan[sp] > 0, r, 0.0)   # wisdom: no senescence target

    # ------------------------------------------------------------------ initial placement
    def place_initial(self, comp, w, seed):
        sps, js, is_ = [], [], []
        k = 0
        cand = np.argwhere(w["unlocked"] & (w["h"] < self.wade) & ~w["rim"])
        wet_order = np.argsort(-(w["h"] + 0.02 * w["theta"])[cand[:, 0], cand[:, 1]], kind="stable")
        for name in SP:
            cnt = comp.get(name, 0)
            for _ in range(cnt):
                if name == "sakana":   # fish start in the wettest available cells
                    jj, ii = cand[wet_order[k % len(wet_order)]]
                else:
                    u = rng.u01(seed, rng.INIT, 0, k)[0]
                    jj, ii = cand[int(u * len(cand)) % len(cand)]
                sps.append(SP.index(name))
                js.append(jj)
                is_.append(ii)
                k += 1
        sp = np.array(sps, int)
        self.pop.add(sp, np.array(js, int), np.array(is_, int), self.init_e[sp], np.full(len(sp), 0.20), 0)  # [confirmed] mass .20
        # [confirmed] every new grass cat seeds min(N,.025) of nutrient into grass resource
        self._seed_grass(w, sp == GRASS)
        from .behavior import initialize
        initialize(self, seed)

    def _seed_grass(self, w, which):
        for k in np.flatnonzero(which):
            j, i = self.pop.j[k], self.pop.i[k]
            s = min(w["N"][j, i], 0.025)
            w["N"][j, i] -= s
            w["G"][j, i] += s

    # ------------------------------------------------------------------ daily step
    def step(self, w, day, seed, env):
        p = self.pop
        n0, n1 = w["N"].shape
        st = {"births": 0, "deaths_starvation": 0, "deaths_stress": 0, "deaths_old": 0, "deaths_collapse": 0,
              "plant_use_m3": 0.0, "production": 0.0, "grazed": 0.0, "decomposed": 0.0, "spawned": 0,
              "catnip_in_kg": 0.0, "wisdom_water_m3": 0.0, "wisdom_event": "", "chie_spawn_kg": 0.0, "births_by_sp": np.zeros(8, int),
              "deaths_by_sp": np.zeros(8, int), "sp_produced": np.zeros(8), "sp_grazed": np.zeros(8), "sp_decomposed": np.zeros(8),
              "sp_moved": np.zeros(8, int), "sp_transport_kg": np.zeros(8), "transport_events": []}
        A = w["A"]
        if len(p) == 0:
            self.motion_plan = []
            self.feeding_plan = []
            self.behavior = {}
            self._wisdom(w, day, seed, st)
            self._spawn_grass(w, day, seed, st, env)
            self.stats = st
            return st
        # canonical id order: shares are allocated proportionally (no first-caller advantage) and
        # floating-point sums (bincount / add.at) then run in a fixed order -> bit-identical results
        # whatever order the arrays arrive in.
        p.permute(np.argsort(p.id, kind="stable"))
        p.age = p.age + 1
        p.action = np.zeros(len(p), np.int64)
        p.infl_soil_m3 = np.zeros(len(p))
        p.infl_cover = np.zeros(len(p))
        p.infl_transport_kg = np.zeros(len(p))
        years = p.age / self.dpy
        sen = rng.u01(seed, rng.SENESCENCE, day, p.id) < self.senescence_risk(p.sp, years)
        # Choose and move before feeding: a daily transaction can expose this
        # committed plan to observation playback without re-running ecology.
        from .behavior import update
        update(self, w, day, seed)
        self._move(w, day, seed, years, st)
        J, I = p.j, p.i
        T = w["T"][J, I]
        m = w["moist"][J, I]
        # ---- stress [confirmed formulas, genes fixed at species defaults: tol cold .32/.36 fluff, hot .17]
        cold, hot = np.maximum(0, 13 - T), np.maximum(0, T - 31)
        tol = np.where(T < 13, np.where(p.sp == FUWA, 0.36, 0.32), 0.17)
        tol = np.where(m < 0.3, np.maximum(tol, 0.12), tol)
        tol = np.where(m > 0.72, np.maximum(tol, 0.12), tol)
        env_load = (cold * 0.0006 + hot * 0.0004) * np.maximum(0.35, 1 - tol)
        damage = env_load + 0.0003 * np.maximum(0.35, 1 - tol)
        fuw_cluster = w["fuwa_near"][J, I] & (p.sp == FUWA) & (T < _v(self.S["fuwa"]["cluster_temp_C"]))
        damage = np.where(fuw_cluster, damage * _v(self.S["fuwa"]["cluster_damage_mult"]), damage)
        p.stress = 0.9 * p.stress + 0.1 * (env_load + (m < 0.3) * 0.003 * 0.6 + (m > 0.85) * 0.001)
        gain = np.zeros(len(p))
        mass_gain = np.zeros(len(p))
        flat = J * n1 + I
        # ---- grass production [confirmed formula] x water/nutrient limitation [provisional]
        g = self.S["grass"]
        isg = p.sp == GRASS
        P = np.clip(env["light"] * (0.08 + 0.07 * _v(g["photosynthesis"])) * (0.2 + m) * (w["N"][J, I] + 0.38)
                    * (1 - 0.6 * w["cover"][J, I]) * np.clip((T + 6) / 30, 0.08, 1.25), 0.0005, 0.09) * isg \
            * self.opts.get("production_mult", 1.0)
        wu = P * _v(g["water_use_m_per_unit"])
        dN = np.bincount(flat, P * (_v(g["biomass_frac"]) + _v(g["resource_frac"])), n0 * n1).reshape(n0, n1)
        dW = np.bincount(flat, wu, n0 * n1).reshape(n0, n1)
        fN = np.where(dN > 0, np.minimum(1, w["N"] / np.maximum(dN, 1e-300)), 1)
        fW = np.where(dW > 0, np.minimum(1, w["Ws"] / np.maximum(dW, 1e-300)), 1)
        f = np.minimum(fN, fW)
        Pe = P * f[J, I]
        bio = Pe * _v(g["biomass_frac"])
        res = Pe * _v(g["resource_frac"])
        np.subtract.at(w["N"], (J, I), bio + res)
        _credit(w, "G", (J, I), res)
        np.subtract.at(w["Ws"], (J, I), wu * f[J, I])
        mass_gain += bio
        gain += Pe
        p.action = np.where(Pe > 0, 2, p.action)
        st["sp_produced"] += np.bincount(p.sp, Pe, 8)
        st["production"] = float(Pe.sum())
        st["plant_use_m3"] = float((wu * f[J, I]).sum() * A)
        # ---- grazing on generated resource G (mogumogu always; bird if moist<.72; fish in water habitat)
        hab = (w["h"][J, I] >= _v(self.S["sakana"]["habitat_depth_m"])) | (w["theta"][J, I] >= _v(self.S["sakana"]["habitat_sat"]))
        bite = np.where(p.sp == MOGU, _v(self.S["mogumogu"]["bite"]),
               np.where((p.sp == TORI) & (m < _v(self.S["tori"]["max_moist"])), _v(self.S["tori"]["bite"]),
               np.where((p.sp == SAKANA) & hab, _v(self.S["sakana"]["bite"]), 0.0)))
        bite = np.where(p.energy < 1.0, bite, 0.0)
        dG = np.bincount(flat, bite, n0 * n1).reshape(n0, n1)
        fG = np.where(dG > 0, np.minimum(1, w["G"] / np.maximum(dG, 1e-300)), 1)
        intake = bite * fG[J, I]
        np.subtract.at(w["G"], (J, I), intake)
        _credit(w, "O", (J, I), intake * 0.32)                       # [confirmed] 32% of a bite -> organic
        mass_gain += intake * 0.68
        epu = np.where(p.sp == MOGU, _v(self.S["mogumogu"]["energy_per_bite"]), 0.82)
        gain += intake * epu
        p.action = np.where(intake > 0, 3, p.action)
        st["sp_grazed"] += np.bincount(p.sp, intake, 8)
        st["grazed"] = float(intake.sum())
        # ---- decomposers [confirmed rates]: kinoko, slime on O (fast) and R (slow); fuwa gleans O
        kd, sd, fw = self.S["kinoko"], self.S["slime"], self.S["fuwa"]
        dfast = np.where(p.sp == KINOKO, _v(kd["fast_rate"]) * (0.45 + m),
                np.where(p.sp == SLIME, _v(sd["fast_rate"]) * (0.5 + m) * (0.65 + _v(sd["decomposer"]) * 0.7),
                np.where(p.sp == FUWA, _v(fw["glean"]), 0.0)))
        dslow = np.where(p.sp == KINOKO, _v(kd["slow_rate"]) * (0.45 + m) * _v(kd["decomposer"]),
                np.where(p.sp == SLIME, _v(sd["slow_rate"]) * (0.5 + m) * _v(sd["decomposer"]), 0.0))
        for pool, dem in (("O", dfast), ("R", dslow)):
            D = np.bincount(flat, dem, n0 * n1).reshape(n0, n1)
            fr = np.where(D > 0, np.minimum(1, w[pool] / np.maximum(D, 1e-300)), 1)
            take = dem * fr[J, I]
            np.subtract.at(w[pool], (J, I), take)
            to_n = np.where(p.sp == KINOKO, _v(kd["to_nutrient"]), np.where(p.sp == SLIME, _v(sd["to_nutrient"]), 1 - _v(fw["glean_mass"])))
            _credit(w, "N", (J, I), take * to_n)
            mass_gain += take * (1 - to_n)
            gain += take * np.where(p.sp == KINOKO, _v(kd["energy_per_unit"]), np.where(p.sp == SLIME, _v(sd["energy_per_unit"]), _v(fw["energy_per_unit"])))
            st["decomposed"] += float(take.sum())
            p.action = np.where(take > 0, 4, p.action)
            st["sp_decomposed"] += np.bincount(p.sp, take, 8)
        self.feeding_plan = [{'id': int(p.id[k]), 'position': [int(p.j[k]),int(p.i[k])],
                              'kind': 'eat'} for k in np.flatnonzero(np.isin(p.action, [3,4]))]
        for cid in p.id[np.isin(p.action,[3,4])]:
            if int(cid) in getattr(self, 'behavior', {}): self.behavior[int(cid)]['state'] = 'eating'
        # ---- energy budget [confirmed costs/age factors]
        aef = self.age_factor_energy(p.sp, years)
        dry_pen = np.where(p.sp == SAKANA, np.maximum(0, 0.62 - np.where(hab, 1.0, m)) * _v(self.S["sakana"]["dry_penalty"]) * 0.6, 0)
        stress_ct = (T > 27).astype(float) + (T < 10) + (m > 0.72) + (m < 0.3)
        cost = (self.cost[p.sp] + damage * self.dmg_mult[p.sp] + dry_pen) * aef + 0.0002 * aef * stress_ct
        cost = np.where(p.sp == CHIE, 0.0002 * aef * stress_ct, cost)
        p.energy = np.where(p.sp == MOGU, np.minimum(p.energy + gain, 1.2), p.energy + gain) - cost
        p.mass = p.mass + mass_gain
        exc = np.minimum(np.maximum(p.mass, 0), 0.0005)                 # [confirmed] excretion -> organic
        p.mass -= exc
        _credit(w, "O", (J, I), exc)
        # ---- reproduction (occupancy before births; explicit space capacity K per cell)
        self._reproduce(w, day, seed, years, st)
        # ---- deaths
        p = self.pop
        n_alive_nonchie = int(((p.sp != CHIE)).sum())
        starve = (p.energy <= 0) & (p.sp != CHIE)
        sen = np.concatenate([sen, np.zeros(len(p) - len(sen), bool)])
        old = sen & ~starve & (p.sp != CHIE)
        collapse = (p.sp == CHIE) & (len(p) < _v(self.S["chie"]["collapse_pop"])) & (day > p.born + _v(self.S["chie"]["grace_days"]))
        dead = starve | old | collapse
        if dead.any():
            stress_cause = starve & (p.stress >= 0.004)
            st["deaths_stress"] += int(stress_cause.sum())
            st["deaths_starvation"] += int((starve & ~stress_cause).sum())
            st["deaths_old"] += int(old.sum())
            st["deaths_collapse"] += int(collapse.sum())
            st["deaths_by_sp"] += np.bincount(p.sp[dead], minlength=8)
            _credit(w, "O", (p.j[dead], p.i[dead]), np.maximum(p.mass[dead], 0))   # carcass -> organic
            neg = np.minimum(p.mass[dead], 0).sum()
            assert neg >= -1e-12, "negative carcass mass"
            cause = np.where(collapse, "collapse", np.where(old, "old_age", np.where(stress_cause, "stress", "starvation")))
            for k in np.flatnonzero(dead):                                  # death-event ledger (alive=False)
                self.deaths.append({"day": day, "id": int(p.id[k]), "species": SP[p.sp[k]], "cause": str(cause[k]),
                                    "age": int(p.age[k]), "mass_kg": float(p.mass[k]), "j": int(p.j[k]), "i": int(p.i[k])})
            p.keep(~dead)
        self._spawn_grass(w, day, seed, st, env)
        self._wisdom(w, day, seed, st)
        from .behavior import initialize
        initialize(self, seed)
        self.stats = st
        return st

    # ------------------------------------------------------------------ movement
    def _move(self, w, day, seed, years, st):
        p = self.pop
        j_from, i_from = p.j.copy(), p.i.copy()
        n0, n1 = w["N"].shape
        k = len(p)
        activity = w['weather_activity'][p.j,p.i] if 'weather_activity' in w else 1.0
        go = rng.u01(seed, rng.MOVE, day, p.id) < self.move_p[p.sp] * activity
        # Rest is an intention, not an extra veto over the species' daily
        # movement opportunity: withholding that draw stranded slow decomposers.
        cj = p.j[:, None] + NB[None, :, 0]
        ci = p.i[:, None] + NB[None, :, 1]
        inside = (cj >= 0) & (cj < n0) & (ci >= 0) & (ci < n1)
        cjc, cic = np.clip(cj, 0, n0 - 1), np.clip(ci, 0, n1 - 1)
        z = w["z"]
        ok = inside & w["unlocked"][cjc, cic]
        if 'obstacles' in w:
            ok &= ~w['obstacles'][cjc,cic] | (p.sp == TORI)[:,None]
            ok[:,0] = True  # an existing occupant can always remain in place
        dz = np.abs(z[cjc, cic] - z[p.j, p.i][:, None]) / w["dx"]
        ok &= (dz <= self.walk) | (p.sp == TORI)[:, None]
        wet = w["h"][cjc, cic] > self.wade
        ok &= ~wet | (p.sp == SAKANA)[:, None] | (p.sp == TORI)[:, None]
        # scores
        jitter = rng.u01(seed, rng.MOVE, day + 1_000_000, (p.id[:, None] * 8 + np.arange(5)[None, :]).ravel()).reshape(k, 5)
        sc = jitter * 1e-3
        decision = w.get('_decision_resources', w)
        G, OR = decision["G"][cjc, cic], (decision["O"] + decision["R"])[cjc, cic]
        sc = np.where((p.sp == MOGU)[:, None], G + sc, sc)
        sc = np.where((p.sp == TORI)[:, None], G * (w["moist"][cjc, cic] < 0.72) + sc, sc)
        # Rank usable daily intake, not raw O+R stock. A huge slow-decaying R
        # pool must not hide an accessible O meal for a hungry decomposer.
        moisture_candidates=w['moist'][cjc,cic]
        kd,sd=self.S['kinoko'],self.S['slime']
        fast=np.where((p.sp==KINOKO)[:,None],_v(kd['fast_rate'])*(.45+moisture_candidates),
                      _v(sd['fast_rate'])*(.5+moisture_candidates)*(.65+_v(sd['decomposer'])*.7))
        slow=np.where((p.sp==KINOKO)[:,None],_v(kd['slow_rate'])*(.45+moisture_candidates)*_v(kd['decomposer']),
                      _v(sd['slow_rate'])*(.5+moisture_candidates)*_v(sd['decomposer']))
        usable=np.minimum(decision['O'][cjc,cic],fast)+np.minimum(decision['R'][cjc,cic],slow)
        sc = np.where(((p.sp == KINOKO) | (p.sp == SLIME))[:, None], usable+jitter*1e-6, sc)
        sc = np.where((p.sp == SAKANA)[:, None], w["h"][cjc, cic] + 0.05 * w["theta"][cjc, cic] + sc, sc)
        sc = np.where(((p.sp == GRASS) | (p.sp == CHIE))[:, None], jitter, sc)
        fuwa = p.sp == FUWA
        if fuwa.sum() > 1:
            fj, fi = p.j[fuwa], p.i[fuwa]
            idx = np.flatnonzero(fuwa)
            from .spatial import SpatialIndex
            index = SpatialIndex(fj,fi,idx)
            for a, kk in enumerate(idx):
                if w["T"][p.j[kk], p.i[kk]] < 15:
                    target = index.nearest(int(p.j[kk]),int(p.i[kk]),int(kk))
                    sc[kk] = -np.hypot(cj[kk] - p.j[target], ci[kk] - p.i[target]) + jitter[kk] * 1e-3
                else:
                    sc[kk] = jitter[kk]
        elif fuwa.any():
            sc[fuwa] = jitter[fuwa]
        avoid = np.array([getattr(self,'behavior',{}).get(int(cid),{}).get('state') in ('avoidDanger','avoidingDanger') for cid in p.id])
        thermal = np.maximum(0,13-w['T'][cjc,cic]) + np.maximum(0,w['T'][cjc,cic]-31)
        moisture = np.maximum(0,.3-w['moist'][cjc,cic]) + np.maximum(0,w['moist'][cjc,cic]-.85)
        sc = np.where(avoid[:,None], -thermal-.5*moisture+jitter*1e-3, sc)
        # Goals influence roaming/social destinations. Food selection retains the
        # species intake ranking (including slow/fast decomposer availability).
        for kk,cid in enumerate(p.id):
            rec=getattr(self,'behavior',{}).get(int(cid),{})
            if rec.get('intent')=='seekFood' and p.sp[kk] not in (GRASS,CHIE):
                gj,gi=rec['goal'];sc[kk]=-np.hypot(cj[kk]-gj,ci[kk]-gi)+jitter[kk]*1e-6
            if rec.get('intent') in ('exploring','socializing') and p.sp[kk] not in (GRASS,CHIE,KINOKO,SLIME,SAKANA,TORI) and p.energy[kk]>=.5:
                gj,gi=rec['goal'];sc[kk]=-np.hypot(cj[kk]-gj,ci[kk]-gi)+jitter[kk]*1e-3
        sc = np.where(ok, sc, -np.inf)
        best = np.argmax(sc, axis=1)
        best = np.where(go & np.isfinite(sc[np.arange(k), best]), best, 0)
        p.j = cjc[np.arange(k), best]
        p.i = cic[np.arange(k), best]
        # birds: distant flight up to `flight` cells (Chebyshev) to the best dry grazing cell;
        # landing cell must be unlocked and not deep water (slope does not limit flight) [provisional]
        R = self.flight
        for kk in np.flatnonzero(go & (p.sp == TORI)):
            j0, i0 = j_from[kk], i_from[kk]
            ja, jb, ia, ib = max(0, j0 - R), min(n0, j0 + R + 1), max(0, i0 - R), min(n1, i0 + R + 1)
            rec=getattr(self,'behavior',{}).get(int(p.id[kk]),{})
            if rec.get('intent')=='seekFood':
                gj,gi=rec['goal']
                if ja<=gj<jb and ia<=gi<ib and w['unlocked'][gj,gi] and w['h'][gj,gi]<=self.wade:
                    p.j[kk],p.i[kk]=gj,gi
                    continue
            Gs = decision["G"][ja:jb, ia:ib] * (w["moist"][ja:jb, ia:ib] < 0.72)
            okb = w["unlocked"][ja:jb, ia:ib] & (w["h"][ja:jb, ia:ib] <= self.wade)
            jit = rng.u01(seed, rng.MOVE, day + 2_000_000, p.id[kk] * 1024 + np.arange(Gs.size)).reshape(Gs.shape) * 1e-6
            score = np.where(okb, Gs + jit, -np.inf)
            if np.isfinite(score).any():
                t = np.unravel_index(np.argmax(score), score.shape)
                p.j[kk], p.i[kk] = ja + t[0], ia + t[1]
        moved = (p.j != j_from) | (p.i != i_from)
        p.action = np.where(moved, np.where(p.sp == TORI, 6, 1), p.action)
        st["sp_moved"] += np.bincount(p.sp[moved], minlength=8)
        self.motion_plan = [{'id': int(p.id[k]), 'origin': [int(j_from[k]),int(i_from[k])],
                             'position': [int(p.j[k]),int(p.i[k])]} for k in range(len(p))]
        for k, cid in enumerate(p.id):
            rec = getattr(self, 'behavior', {}).get(int(cid))
            if rec:
                rec['arrived'] = rec.get('goal') == [int(p.j[k]),int(p.i[k])]
                rec['travelled'] = bool(moved[k])
                if moved[k]: rec['state'] = 'moving'

        if not self.effects:
            return
        # conserved nutrient cargo: picked at the origin cell (shared per origin cell if several
        # carriers ask for more than is there), dropped at the destination  [legacy bird .0015*flight,
        # fish .001*aquatic when leaving wet (moist>.62) for drier (<.62) ground]
        want = np.where((p.sp == TORI) & moved, _v(self.S["tori"]["cargo"]) * _v(self.S["tori"]["flight"]),
               np.where((p.sp == SAKANA) & moved & (w["moist"][j_from, i_from] > 0.62) & (w["moist"][p.j, p.i] < 0.62),
                        _v(self.S["sakana"]["cargo"]) * 0.9, 0.0))
        if want.sum() > 0:
            flat = j_from * n1 + i_from
            D = np.bincount(flat, want, n0 * n1).reshape(n0, n1)
            fr = np.where(D > 0, np.minimum(1, w["N"] / np.maximum(D, 1e-300)), 1)
            cargo = want * fr[j_from, i_from]
            np.subtract.at(w["N"], (j_from, i_from), cargo)
            _credit(w, "N", (p.j, p.i), cargo)
            p.infl_transport_kg += cargo
            st["sp_transport_kg"] += np.bincount(p.sp, cargo, 8)
            for kk in np.flatnonzero(cargo > 0):
                st["transport_events"].append((int(p.id[kk]), SP[p.sp[kk]], (int(j_from[kk]), int(i_from[kk])), (int(p.j[kk]), int(p.i[kk])), float(cargo[kk])))

    # ------------------------------------------------------------------ reproduction
    def _reproduce(self, w, day, seed, years, st):
        p = self.pop
        n0, n1 = w["N"].shape
        occ = np.bincount(p.j * n1 + p.i, minlength=n0 * n1).reshape(n0, n1)
        space = np.clip(1 - occ[p.j, p.i] / self.K, 0, 1)
        catnip = _v(self.S["chie"]["catnip_mult"]) if day <= self.catnip_until else 1.0
        enabled = (p.sp != CHIE) & ((p.sp != GRASS) | self.grass_repro)
        elig = enabled & (p.energy > self.e_thr) & (self.repro_age_factor(p.sp, years) > 0) & (day - p.last_birth >= self.cooldown[p.sp])
        p.eligible = elig
        prob = self.base[p.sp] * self.rate_mult * self.repro_age_factor(p.sp, years) * catnip * space
        birth = elig & (rng.u01(seed, rng.REPRO, day, p.id) < prob)
        idx = np.flatnonzero(birth)
        limit = getattr(self, "max_population", None)
        if limit is not None:
            slots = max(0, int(limit) - len(p))
            # Choose before charging parents; rejected births retain all energy and mass.
            # Independent counter stream avoids favouring a species or array order.
            if len(idx) > slots:
                priority = rng.u01(seed, 11, day, p.id[idx])
                idx = idx[np.lexsort((p.id[idx], priority))[:slots]]
        if len(idx) == 0:
            return
        idx = idx[np.argsort(p.id[idx], kind="stable")]               # stable id order for new ids
        omass = np.minimum(np.maximum(p.mass[idx], 0), self.newborn_max)
        p.energy[idx] -= self.e_cost
        p.mass[idx] -= omass
        p.last_birth[idx] = day
        p.action[idx] = 5
        u = rng.u01(seed, rng.BIRTHPOS, day, p.id[idx])
        d = (u * 5).astype(int)
        bj = np.clip(p.j[idx] + NB[d, 0], 0, n0 - 1)
        bi = np.clip(p.i[idx] + NB[d, 1], 0, n1 - 1)
        slope_ok = (np.abs(w["z"][bj, bi] - w["z"][p.j[idx], p.i[idx]]) / w["dx"] <= self.walk) | (p.sp[idx] == TORI)
        okc = w["unlocked"][bj, bi] & ((w["h"][bj, bi] <= self.wade) | (p.sp[idx] == SAKANA)) & slope_ok   # same rules as moving
        bj = np.where(okc, bj, p.j[idx])
        bi = np.where(okc, bi, p.i[idx])
        sp = p.sp[idx]
        start = len(p)
        p.add(sp, bj, bi, self.init_e[sp], omass, day)
        newg = np.flatnonzero((np.arange(len(p)) >= start) & (p.sp == GRASS))
        for kk in newg:                                               # [confirmed] new grass seeds resource
            s = min(w["N"][p.j[kk], p.i[kk]], 0.025)
            w["N"][p.j[kk], p.i[kk]] -= s
            _credit(w, "G", (p.j[kk],p.i[kk]), s)
        st["births"] += len(idx)
        st["births_by_sp"] += np.bincount(sp, minlength=8)

    # ------------------------------------------------------------------ spontaneous grass [confirmed rule, OFF by default]
    def _spawn_grass(self, w, day, seed, st, env):
        limit = getattr(self, "max_population", None)
        if not self.grass_spawn or (limit is not None and len(self.pop) >= limit):
            return
        ng = int((self.pop.sp == GRASS).sum())
        if ng >= 3:
            return
        sites = w["unlocked"] & (w["T"] >= 8) & (w["T"] <= 30) & (w["moist"] >= 0.35) & (w["moist"] <= 0.82) & (w["N"] >= 0.08)
        if not sites.any():
            return
        pr = [0.018, 0.012, 0.006][ng]
        u = rng.u01(seed, rng.SPAWN, day, [0, 1])
        if u[0] >= pr:
            return
        cand = np.argwhere(sites)
        jj, ii = cand[int(u[1] * len(cand)) % len(cand)]
        w["N"][jj, ii] -= 0.055
        self.pop.add(np.array([GRASS]), np.array([jj]), np.array([ii]), np.array([self.init_e[GRASS]]), np.array([0.055]), day)
        s = min(w["N"][jj, ii], 0.025)
        w["N"][jj, ii] -= s
        _credit(w, "G", (jj,ii), s)
        st["spawned"] += 1

    # ------------------------------------------------------------------ wisdom clock [confirmed rules; water amount provisional]
    def _wisdom(self, w, day, seed, st):
        if not self.chie_enabled or day % _v(self.S["chie"]["period_days"]) != 0:
            return
        cs = self.S["chie"]
        p = self.pop
        has = (p.sp == CHIE).any()
        if not has:
            ordinary = int((p.sp != CHIE).sum())
            cells = w["unlocked"] & (w["N"] >= _v(cs["spawn_nutrient"]))
            limit = getattr(self, "max_population", None)
            if ordinary >= 1 and cells.any() and (limit is None or len(p) < limit):
                flatN = np.where(cells, w["N"], -1).ravel()
                k = int(np.argmax(flatN))
                jj, ii = divmod(k, w["N"].shape[1])
                w["N"][jj, ii] -= _v(cs["spawn_nutrient"])
                p.add(np.array([CHIE]), np.array([jj]), np.array([ii]), np.array([1.2]), np.array([_v(cs["spawn_nutrient"])]), day)
                st["wisdom_event"] = "spawn"
                st["chie_spawn_kg"] = _v(cs["spawn_nutrient"])
            return
        nonw = int((p.sp != CHIE).sum())
        bio = w["biome_id"]
        total = bio.size
        desert = float((bio == 1).sum()) / total
        cold = float((bio == 3).sum()) / total
        if nonw < 30 and self.catnip_charges > 0:
            self.catnip_charges -= 1
            self.catnip_until = day + _v(cs["catnip_days"])
            tgt = np.flatnonzero(p.sp != CHIE)
            k = tgt[np.argmin(p.id[tgt])] if len(tgt) else np.flatnonzero(p.sp == CHIE)[0]
            _credit(w, "O", (p.j[k],p.i[k]), _v(cs["catnip_mass"]))
            st["catnip_in_kg"] = _v(cs["catnip_mass"])
            st["wisdom_event"] = "catnip"
        elif desert >= _v(cs["advice_share"]):
            mask = (bio == 1) & w["unlocked"]
            add = _v(cs["water_add_m"])
            w["h"][mask] += add
            st["wisdom_water_m3"] = float(mask.sum() * add * w["A"])
            st["wisdom_event"] = "water"
        elif cold >= _v(cs["advice_share"]):
            k = np.flatnonzero(p.sp == CHIE)[0]
            self.fires.append((int(p.j[k]), int(p.i[k]), day + _v(cs["fire_days"])))
            self.fires = self.fires[-3:]
            st["wisdom_event"] = "fire"
        else:
            st["wisdom_event"] = "observe"
