import { MODES } from './time.js';
export const AMBIENT = ['look','groom','stretch','roll','tail','blink','idle'];
const sleeping = new Set(['rest','resting']);
const eating = new Set(['eat','eating']);
// No imports from the ecology, no world writes, no ecology RNG calls.
export class Presentation {
  constructor() { this.live = new Map(); this.pool = []; this.speed = 1; this.elapsed = 0; this.sinceSync = Infinity; this.paused = false; this.summary = {}; this.reassignMs=0; this.reassignments=0; }
  setMode(speed) { this.speed = speed; this.sinceSync = Infinity; for (const r of this.live.values()) r.walking=false; }
  sync(st, force = false) {
    this.latest = st;
    const seen = new Set(st.cats.id);
    for (const [id, r] of this.live) if (!seen.has(id)) { this.live.delete(id); r.alive = false; r.selected=false; this.pool.push(r); }
    this.pool.length=Math.min(this.pool.length,Math.max(16,this.live.size));
    if (!force && this.speed !== .05 && this.sinceSync < 1 / MODES[String(this.speed)].hz) return;
    this.sinceSync = 0;
    const allocationStart=performance.now();
    const c = st.cats;
    for (let k = 0; k < c.id.length; k++) {
      const id = c.id[k]; let r = this.live.get(id);
      if (!r) { r = this.pool.pop() || {}; for (const key of Object.keys(r)) delete r[key]; Object.assign(r, {id, phase: (id * .61803398875) % 1 * Math.PI * 2, gait: 0, walking:false, bob:0, gesture:0, heading: ((id * 2654435761) >>> 0) % 360, selected:false, spriteFrame:0, animation:'birth', animationStart:this.elapsed, progress:0, priority:0, bornAt:this.elapsed, scaleX:1, scaleY:1, rotation:0, direction:0}); this.live.set(id, r); this.reassignments++; }
      const x = (c.i[k] + .5) * st.cell_m, y = (c.j[k] + .5) * st.cell_m;
      const moved = r.alive && (x !== r.targetX || y !== r.targetY);
      if (moved) r.heading = (Math.atan2(x - r.targetX, -(y - r.targetY)) * 180 / Math.PI + 360) % 360;
      // Normal/high speed explicitly teleport, retaining real-time gesture/gait phase.
      const oldX=r.x,oldY=r.y,oldBehavior=r.behavior;
      Object.assign(r, {alive: true, targetX: x, targetY: y, x, y, k, sp: st.species[c.sp[k]], behavior: c.behavior?.[k] || 'idle', goal:c.goals?.[k]?.slice() || [c.j[k],c.i[k]]});
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
      r.behavior=r.walking?'move':(seconds>299 && this.plan.feeds?.some(f=>f.id===r.id)?'eat':(this.plan.actions?.[r.id]||'rest'));
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
      const ambient=AMBIENT[r.gesture];
      const animation=this.elapsed-r.bornAt<.6?'birth':r.walking?'walk':eating.has(r.behavior)?'eat':sleeping.has(r.behavior)?'sleep':ambient;
      if (r.animation!==animation) {r.animation=animation;r.animationStart=this.elapsed;}
      r.progress=this.elapsed-r.animationStart;
      r.spriteFrame=0; // source atlas contains one static frame per direction
      r.scaleX=r.scaleY=1;r.rotation=0;
      if (animation==='walk')r.scaleY=1+.025*Math.sin(r.gait);
      else if (animation==='birth')r.scaleX=r.scaleY=.6+.4*Math.min(1,r.progress/.6);
      else if (animation==='eat'||animation==='groom')r.rotation=.04*Math.sin(r.phase*3);
      else if (animation==='stretch') {r.scaleY=1+.06*Math.sin(r.phase*2);r.scaleX=1-.03*Math.sin(r.phase*2);}
      else if (animation==='roll')r.rotation=.08*Math.sin(r.phase);
      else if (animation==='sleep')r.scaleY=.94+.01*Math.sin(r.phase*1.5);
      // Eye and tail frames are unavailable: no fictitious frame indices.
      r.priority=r.selected?10:0;
    }
  }
}
