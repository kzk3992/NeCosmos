import test from 'node:test';
import assert from 'node:assert/strict';
import {PlanetClock, MODES, ModeSwitch} from '../public/js/time.js';
import {Presentation} from '../public/js/presentation.js';
for (const speed of Object.keys(MODES)) test(`time conversion ${speed}`,()=>{
 const c=new PlanetClock(+speed);
 for(let i=0;i<600;i++) c.advance(MODES[speed].seconds/600,true);
 assert.equal(c.take(),1);assert.ok(c.acc<1e-8);
 c.advance(10000,false);assert.equal(c.take(),0);
 c.advance(MODES[speed].seconds*.8,true);c.setMode(100);assert.equal(c.take(),0);
});
test('FPS/partition independent integer ticks and pause',()=>{
 for(const fps of [15,30,60,144]) {const c=new PlanetClock(100);let days=0;for(let n=0;n<fps*15;n++){c.advance(1/fps,true);days+=c.take();}assert.equal(days,100);}
});
test('mode switch coalesces pending requests',async()=>{
 let release;const gate=new Promise(r=>release=r);const calls=[];
 const s=new ModeSwitch(async latest=>{await gate;calls.push(latest());});
 const a=s.request(5),b=s.request(20),c=s.request(100);release();await Promise.all([a,b,c]);assert.deepEqual(calls,[100]);
});
const world=(ids=[1])=>({day:0,cell_m:.5,species:['grass'],cats:{id:ids,sp:ids.map(()=>0),i:ids.map(()=>2),j:ids.map(()=>2),behavior:ids.map(()=>'idle')}});
test('teleport is throttled without resetting gesture phase; pooling removes dead',()=>{
 const p=new Presentation();p.setMode(100);const w=world();const before=JSON.stringify(w);p.sync(w,true);p.frame(.1);const r=p.live.get(1),phase=r.phase;
 const next=world();next.cats.i[0]=20;p.sync(next);assert.equal(r.x,1.25);p.frame(1);assert.equal(r.x,10.25);assert.ok(r.phase>phase);
 p.sync(world([]),true);assert.equal(p.live.size,0);assert.equal(p.pool.length,1);p.sync(world([2]),true);assert.equal(p.live.get(2),r);assert.equal(JSON.stringify(w),before);
});
test('observation walks at .25 metres/s and gait tracks distance, then waits',()=>{
 const p=new Presentation();p.setMode(.05);p.sync(world(),true);p.setPlan({day:1,cell_m:.5,moves:[{id:1,origin:[2,2],position:[2,3]}]},0);
 p.sampleObservation(1/300);assert.equal(p.live.get(1).x,1.5);assert.equal(p.live.get(1).walking,true);
 p.sampleObservation(2/300);assert.equal(p.live.get(1).x,1.75);assert.equal(p.live.get(1).walking,false);
 const phase=p.live.get(1).phase;p.setMode(100);p.frame(1);assert.ok(Math.abs(p.live.get(1).phase-phase-1)<1e-10);
});
test('observation intake pose survives render frames, mode switch clears walking',()=>{
 const p=new Presentation();p.setMode(.05);p.sync(world(),true);
 p.setPlan({day:1,cell_m:.5,moves:[{id:1,origin:[2,2],position:[2,3]}],feeds:[{id:1}]},0);
 p.sampleObservation(299.5/300);p.frame(.016);assert.equal(p.live.get(1).behavior,'eat');
 p.sampleObservation(.5/300);assert.ok(p.live.get(1).walking);p.setMode(100);assert.equal(p.live.get(1).walking,false);
});
