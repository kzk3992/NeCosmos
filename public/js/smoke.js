// Browser smoke test for NeCosmos v0.10 (open /?smoke=1). Result: window.NeCosmosSmoke = {ok, checks, ms}.
// Uses only the public window.NeCosmos API; the save slot is backed up and restored afterwards.
export async function runSmoke() {
  const N = window.NeCosmos, t0 = performance.now(), checks = [];
  const check = (name, ok, value) => { checks.push({ name, ok: !!ok, value }); console[ok ? "log" : "error"]("[smoke]", ok ? "PASS" : "FAIL", name, value ?? ""); };
  const backup = [localStorage.getItem("necosmos_v010_save"), localStorage.getItem("necosmos_v010_meta")];
  try {
    await N.ready;
    check("engine ready", N.status.ready, N.status.engine);
    await N.newWorld({ terrain: "initial_river", climate: "wet", composition: "all8", seed: 90102 });
    const s0 = N.state();
    check("day 0 existing river visible", s0.river.reduce((a, b) => a + b, 0) >= 30, s0.river.reduce((a, b) => a + b, 0));
    let s = await N.step(1);
    check("step 1 day", s.day === 1, s.day);
    const finite = (a) => a.every(Number.isFinite);
    check("fields finite", finite(s.z) && finite(s.h), null);
    s = await N.step(299);
    check("day 300 reached", s.day === 300, s.day);
    check("300-day evaluation recorded (observer)", N.evaluations().some((e) => e.day === 300), N.evaluations().length);
    check("residuals tiny", s.residual.water_m3 < 1e-9 && s.residual.soil_m3 < 1e-9 && s.residual.matter_kg < 1e-8, s.residual);
    const u = await N.unlock(2);
    check("unlock level 2", u.ok && N.state().unlocked.reduce((a, b) => a + b, 0) === 512, N.state().unlocked.reduce((a, b) => a + b, 0));
    let placed = null;
    for (const [x, y] of [[7, 9.5], [9.5, 9.5], [6.5, 6.5], [9.5, 6.5], [8, 10.5]]) {
      const r = await N.place("cat_tower_01", x, y, 0);
      if (r.ok) { placed = r.pid; break; }
    }
    check("tower placed", placed !== null, placed);
    const o = N.state().objects.find((q) => q.pid === placed);
    check("tower platforms in world coords", o && o.platformsWorld.length === 2, o?.platformsWorld);
    check("protection active", N.state().protection.some((p) => p > 0.9), null);
    await N.save();
    const h1 = await N.hash();
    await N.step(50);
    const h2 = await N.hash();
    await N.load();
    check("load restores exact state", (await N.hash()) === h1, h1);
    await N.step(50);
    check("continuation after load identical", (await N.hash()) === h2, h2);
    const rm = await N.remove(placed);
    check("remove releases protection", rm.ok && !N.state().protection.some((p) => p > 0.05), null);
    s = await N.step(900);
    check("day 1250 reached", s.day === 1250, s.day);
    check("residuals tiny at end", s.residual.water_m3 < 1e-9 && s.residual.soil_m3 < 1e-9 && s.residual.matter_kg < 1e-8, s.residual);
  } catch (e) {
    check("no exception", false, String(e));
  } finally {
    backup[0] === null ? localStorage.removeItem("necosmos_v010_save") : localStorage.setItem("necosmos_v010_save", backup[0]);
    backup[1] === null ? localStorage.removeItem("necosmos_v010_meta") : localStorage.setItem("necosmos_v010_meta", backup[1]);
  }
  window.NeCosmosSmoke = { ok: checks.every((c) => c.ok), checks, ms: Math.round(performance.now() - t0) };
  document.documentElement.dataset.smokeResult = JSON.stringify(window.NeCosmosSmoke);
  console.log("[smoke] done", window.NeCosmosSmoke);
  return window.NeCosmosSmoke;
}
