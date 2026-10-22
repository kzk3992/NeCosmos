"""Daily hydrology + sediment transport on the cell grid (finite volume, synchronous).

Units: lengths m, volumes m^3 (cell area A = dx^2). One call = one day in n substeps.
The pipe coefficient is defined PER DAY: c_sub = pipe_coeff_per_day / n_sub (stability needs
c_sub <= 0.25), so changing n_sub changes resolution, not the transport rate.

Per substep (fluxes from the previous substep's state, all computed, then applied):
  0. exfiltration:  Ws above field capacity (fc * s * retention) -> surface h (conserved)
  1. precipitation: falls in the first `storm_substeps` substeps (intensity R/storm); where air T < 0
                    it is stored as snowpack (water equivalent); snow melts at ddf*max(T,0) per day
                    into h (ledger.rain external; snow is a storage term)              [provisional]
  2. infiltration:  I = min(h, ksat*(1+b*cover)*frozen/n, cap - Ws), frozen = frozen_factor if T<0
  2b interflow:     lateral soil water flow down the hydraulic head (b+s+h) gradient: fraction k_if/n * gradient of donor Ws to each lower
                    neighbour (Jacobi, donor-limited); receivers above capacity exfiltrate   [provisional]
  3. routing:       head H = b + s + h; face flux q = c_sub*A*(H_hi - H_lo); rim cells drain through
                    outer faces q = c_sub*A*h*faces (ledger.outflow); outflows scaled to <= h*A.
  4. sediment:      capacity C = k_cap * Qout * max(slope, s_min); erosion k_e*(C-S)+ *(1-hp*hard)
                    *(1-cp*cover)*(1-prot) from soil only; deposition k_d*(S-C)+ *(1-prot); both
                    charged to the shared daily |dz| budget (soilmove); S advected with the same
                    scaled water fractions; outer faces -> ledger.sed_export.
  5. evaporation:   surface min(h, Epot/n*em); soil f_se*(Epot/n*em - Es)*(Ws/cap).
Rivers use the day's NET signed face flux (back-and-forth exchange cancels), returned as Q/dirs.
Clamps at 0 only absorb floating roundoff (asserted <= tolerance, recorded in st["roundoff"]).
"""
import numpy as np

from ..terrain import soilmove

TOL_H = 1e-12      # m of water / sediment volume tolerance for roundoff clamps


def _neighbour_slopes(z, dx):
    s = np.zeros_like(z)
    d = (z[:, :-1] - z[:, 1:]) / dx
    s[:, :-1] = np.maximum(s[:, :-1], d)
    s[:, 1:] = np.maximum(s[:, 1:], -d)
    d = (z[:-1, :] - z[1:, :]) / dx
    s[:-1, :] = np.maximum(s[:-1, :], d)
    s[1:, :] = np.maximum(s[1:, :], -d)
    return s


def _clamp(arr, st, key, scale):
    m = float(arr.min())
    assert m >= -TOL_H * max(scale, 1.0), f"substantive negative {key}: {m}"
    if m < 0:
        st["roundoff"][key] += float(-np.minimum(arr, 0).sum())
        arr = np.maximum(arr, 0.0)
    return arr


def daily(st, cfg, rain_m, epot_m, erosion=True):
    hy, se, so = cfg["hydrology"], cfg["sediment"], cfg["soil"]
    n_sub = hy["substeps"]
    A, dx = st["A"], st["dx"]
    c = hy["pipe_coeff_per_day"] / n_sub
    assert c <= 0.25 + 1e-12, "pipe coefficient per substep must be <= 0.25 for stability"
    rim, edge_faces, prot = st["rim"], st["edge_faces"], st["protection"]
    fc = so["field_capacity"]
    led = dict(rain=0.0, infil=0.0, exfil=0.0, outflow=0.0, evap_surface=0.0, evap_soil=0.0, sed_export=0.0,
               eroded=0.0, deposited=0.0, throttled=0.0, snowfall=0.0, melt=0.0, interflow=0.0)
    T = st.get("T_air", np.full_like(st["h"], 10.0))
    storm = max(1, min(hy.get("storm_substeps", n_sub), n_sub))
    frozen = np.where(T < 0, hy.get("frozen_ksat_factor", 1.0), 1.0)
    cold = T < 0
    melt_day = hy.get("melt_ddf_m_per_C_day", 0.003) * np.maximum(T, 0)
    k_if = hy.get("interflow_per_day", 0.0) / n_sub
    n0, n1 = st["h"].shape
    Fx = np.zeros((n0, n1 - 1))          # net signed face flux over the day (>0: i+1 -> i)
    Fy = np.zeros((n0 - 1, n1))
    Fo = np.zeros((n0, n1))
    gross = np.zeros((n0, n1))
    ero = np.zeros((n0, n1))
    dep = np.zeros((n0, n1))
    for sub in range(n_sub):
        led["exfil"] += soilmove.exfiltrate(st, fc)
        h, s, Ws = st["h"], st["soil"], st["Ws"]
        r = rain_m / storm if sub < storm else 0.0
        led["rain"] += r * A * h.size
        snowfall = np.where(cold, r, 0.0)
        st["snow"] = st["snow"] + snowfall
        h = h + (r - snowfall)
        melt = np.minimum(st["snow"], melt_day / n_sub)
        st["snow"] = st["snow"] - melt
        h = h + melt
        led["snowfall"] += float(snowfall.sum() * A)
        led["melt"] += float(melt.sum() * A)
        cap = fc * s * st["retention"]
        inf = np.minimum(np.minimum(h, hy["ksat_m_per_day"] * (1 + hy["cover_infiltration_bonus"] * st["cover"]) * frozen / n_sub),
                         np.maximum(cap - Ws, 0))
        h = h - inf
        Ws = Ws + inf
        led["infil"] += float(inf.sum() * A)
        if k_if > 0:
            zs = st["bedrock"] + s + h                     # hydraulic head (flat under still water)
            gx = (zs[:, 1:] - zs[:, :-1]) / dx            # >0: i+1 higher -> flows i+1 -> i
            gy = (zs[1:, :] - zs[:-1, :]) / dx
            fx = k_if * gx                                 # signed fraction of the donor's Ws
            fy = k_if * gy
            outf = np.zeros_like(Ws)
            outf[:, 1:] += np.maximum(fx, 0)
            outf[:, :-1] += np.maximum(-fx, 0)
            outf[1:, :] += np.maximum(fy, 0)
            outf[:-1, :] += np.maximum(-fy, 0)
            scl = np.where(outf > 1.0, 1.0 / np.maximum(outf, 1e-300), 1.0)
            qx = np.where(fx > 0, fx * scl[:, 1:] * Ws[:, 1:], fx * scl[:, :-1] * Ws[:, :-1])   # m water depth moved
            qy = np.where(fy > 0, fy * scl[1:, :] * Ws[1:, :], fy * scl[:-1, :] * Ws[:-1, :])
            dW = np.zeros_like(Ws)
            dW[:, :-1] += qx
            dW[:, 1:] -= qx
            dW[:-1, :] += qy
            dW[1:, :] -= qy
            Ws = _clamp(Ws + dW, st, "water_h", float(Ws.max()))
            led["interflow"] += float((np.abs(qx).sum() + np.abs(qy).sum()) * A)
        z = st["bedrock"] + s
        H = z + h
        qx = c * A * (H[:, 1:] - H[:, :-1])
        qy = c * A * (H[1:, :] - H[:-1, :])
        qo = c * A * h * edge_faces
        out = np.zeros_like(h)
        out[:, 1:] += np.maximum(qx, 0)
        out[:, :-1] += np.maximum(-qx, 0)
        out[1:, :] += np.maximum(qy, 0)
        out[:-1, :] += np.maximum(-qy, 0)
        out += qo
        avail = h * A
        scale = np.where(out > avail, avail / np.maximum(out, 1e-300), 1.0)
        qx = np.where(qx > 0, qx * scale[:, 1:], qx * scale[:, :-1])
        qy = np.where(qy > 0, qy * scale[1:, :], qy * scale[:-1, :])
        qo = qo * scale
        out_s = out * scale
        dvol = -qo
        dvol[:, :-1] += qx
        dvol[:, 1:] -= qx
        dvol[:-1, :] += qy
        dvol[1:, :] -= qy
        Fx += qx
        Fy += qy
        Fo += qo
        gross += out_s
        led["outflow"] += float(qo.sum())
        st["h"], st["Ws"] = h, Ws
        # sediment exchange (shared daily budget) then advection with the water fractions
        if erosion:
            slope = np.maximum(_neighbour_slopes(z, dx), se["min_slope"])
            C = se["k_cap"] * out_s * slope
            free = (~rim) * (1 - prot)
            S = st["sed"]
            e_want = se["k_erode"] * np.maximum(C - S, 0) * (1 - se["hardness_protect"] * st["hardness"]) \
                * (1 - se["cover_protect"] * st["cover"]) * free
            e = soilmove.local_exchange(st, e_want, +1)
            S = st["sed"]
            d_want = se["k_dep"] * np.maximum(S - C, 0) * free
            d = soilmove.local_exchange(st, d_want, -1)
            led["throttled"] += float((e_want - e).sum() + (d_want - d).sum())
            ero += e
            dep += d
            led["eroded"] += float(e.sum())
            led["deposited"] += float(d.sum())
        S = st["sed"]
        frac = np.where(avail > 0, np.minimum(out_s / np.maximum(avail, 1e-300), 1.0), 0.0)
        share = np.where(out_s > 0, S * frac / np.maximum(out_s, 1e-300), 0.0)
        sx = np.where(qx > 0, qx * share[:, 1:], qx * share[:, :-1])
        sy = np.where(qy > 0, qy * share[1:, :], qy * share[:-1, :])
        so_out = qo * share
        dS = -so_out
        dS[:, :-1] += sx
        dS[:, 1:] -= sx
        dS[:-1, :] += sy
        dS[1:, :] -= sy
        st["sed"] = _clamp(S + dS, st, "sed", float(S.max()))
        led["sed_export"] += float(so_out.sum())
        h = _clamp(st["h"] + dvol / A, st, "water_h", float(st["h"].max()))
        ep = epot_m / n_sub * st["evap_mult"]
        es = np.minimum(h, ep)
        h = h - es
        cap = fc * st["soil"] * st["retention"]
        eso = np.minimum(st["Ws"], (ep - es) * hy["soil_evap_frac"] * np.clip(st["Ws"] / np.maximum(cap, 1e-12), 0, 1))
        st["Ws"] = st["Ws"] - eso
        st["h"] = h
        led["evap_surface"] += float(es.sum() * A)
        led["evap_soil"] += float(eso.sum() * A)
    led["exfil"] += soilmove.exfiltrate(st, fc)
    # net daily outflow per cell and by direction (E, W, N, S, outside)
    dirs = np.zeros((5, n0, n1))
    dirs[0][:, :-1] = np.maximum(-Fx, 0)
    dirs[1][:, 1:] = np.maximum(Fx, 0)
    dirs[2][:-1, :] = np.maximum(-Fy, 0)
    dirs[3][1:, :] = np.maximum(Fy, 0)
    dirs[4] = Fo
    Q = dirs.sum(0)
    return {"Q": Q, "Q_gross": gross, "dirs": dirs, "ero": ero, "dep": dep, "ledger": led}


def creep(st, cfg):
    """Daily hillslope creep + repose slumping through the shared budget (soilmove)."""
    se = cfg["sediment"]
    A, dx = st["A"], st["dx"]
    z = st["bedrock"] + st["soil"]
    k, rep = se["creep_coeff"], se["repose_slope"]
    qs = []
    for axis in (1, 0):
        dz = np.diff(z, axis=axis)
        qs.append(k * A * dz + 0.25 * A * np.sign(dz) * np.maximum(np.abs(dz) - rep * dx, 0))
    return soilmove.transfer_faces(st, qs[0], qs[1], frozen=st["rim"])
