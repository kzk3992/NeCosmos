import { MODES } from './time.js';
// No imports from the ecology, no world writes, no ecology RNG calls.
export class Presentation {
  constructor() { this.live = new Map(); this.pool = []; this.speed = 1; this.elapsed = 0; this.sinceSync = Infinity; this.paused = false; this.summary = {}; this.reassignMs=0; this.reassignments=0; }
  setMode(speed) { this.speed = speed; this.sinceSync = Infinity; for (const r of this.live.values()) r.walking=false; }
  sync(st, force = false) {
    this.latest = st;
    const seen = new Set(st.cats.id);
    for (const [id, r] of this.live) if (!seen.has(id)) { this.live.delete(id); r.alive = false; this.pool.push(r); }
    if (!force && this.speed !== .05 && this.sinceSync < 1 / MODES[String(this.speed)].hz) return;
    this.sinceSync = 0;
    const allocationStart=performance.now();
    const c = st.cats;
    for (let k = 0; k < c.id.length; k++) {
      const id = c.id[k]; let r = this.live.get(id);
      if (!r) { r = this.pool.pop() || {}; Object.assign(r, {id, phase: (id * .61803398875) % 1 * Math.PI * 2, gait: 0, walking:false, bob:0, gesture:0, heading: ((id * 2654435761) >>> 0) % 360}); this.live.set(id, r); this.reassignments++; }
      const x = (c.i[k] + .5) * st.cell_m, y = (c.j[k] + .5) * st.cell_m;
      const moved = r.alive && (x !== r.targetX || y !== r.targetY);
      if (moved) r.heading = (Math.atan2(x - r.targetX, -(y - r.targetY)) * 180 / Math.PI + 360) % 360;
      // Normal/high speed explicitly teleport, retaining real-time gesture/gait phase.
      const oldX=r.x,oldY=r.y,oldBehavior=r.behavior;
      Object.assign(r, {alive: true, targetX: x, targetY: y, x, y, k, sp: st.species[c.sp[k]], behavior: c.behavior?.[k] || 'idle'});
      if (!force && this.speed===.05 && Number.isFinite(oldX)) {r.x=oldX;r.y=oldY;r.behavior=oldBehavior;}
    }
    this.reassignMs=performance.now()-allocationStart;
    this.summary = (st.behaviorEvents || []).reduce((a, e) => { a[e.kind] = (a[e.kind] || 0) + 1; return a; }, {});
  }
  setPlan(plan, day) { this.plan = plan; this.planDay = day; }
  sampleObservation(fraction) {
    if (this.speed !== .05 || !this.plan || this.plan.day !== this.planDay+1) return;
    // A short move followed by a long stationary day, never a 300-second crawl.
    const seconds = fraction * 300, d = this.plan.cell_m;
    for (const m of this.plan.moves) {
      const r=this.live.get(m.id); if (!r) continue;
      const x0=(m.origin[1]+.5)*d,y0=(m.origin[0]+.5)*d;
      const x1=(m.position[1]+.5)*d,y1=(m.position[0]+.5)*d;
      const distance=Math.hypot(x1-x0,y1-y0), duration=distance/.25;
      const t=duration ? Math.min(1,seconds/duration) : 1;
      r.x=x0+(x1-x0)*t; r.y=y0+(y1-y0)*t;
      r.walking=t<1 && distance>0;
      r.gait=(distance*t/.12)*Math.PI*2;
      if (distance) r.heading=(Math.atan2(x1-x0,-(y1-y0))*180/Math.PI+360)%360;
      r.behavior=r.walking?'move':(seconds>299 && this.plan.feeds?.some(f=>f.id===r.id)?'eat':'rest');
    }
  }
  frame(dt) {
    if (this.paused) return;
    this.elapsed += dt; this.sinceSync += dt;
    if (this.latest) this.sync(this.latest);
    for (const r of this.live.values()) {
      // Gestures always use real seconds. Rendering never consumes the counter RNG.
      r.phase += dt;
      r.bob = .008 * Math.sin(r.phase * 2);
      r.gesture = Math.floor((r.phase + r.id) / 7) % 7;
    }
  }
}
