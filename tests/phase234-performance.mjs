import {chromium} from 'playwright';import fs from 'node:fs';import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const cdp=await browser.newBrowserCDPSession();
async function memory(){const {processInfo}=await cdp.send('SystemInfo.getProcessInfo');let pss=0;for(const p of processInfo){try{pss+=Number(fs.readFileSync(`/proc/${p.id}/smaps_rollup`,'utf8').match(/^Pss:\s+(\d+)/m)[1])*1024;}catch{}}return {browserPssBytes:pss};}
const page=await browser.newPage({viewport:{width:1280,height:800}});const fatal=[];page.on('pageerror',e=>fatal.push(String(e)));await page.goto('http://127.0.0.1:8080/?smoke=stress');await page.waitForFunction(()=>window.NeCosmos?.status.ready&&NeCosmos.status.day!==undefined,null,{timeout:120000});await page.evaluate(()=>NeCosmos.ready);
const out=[];const output=process.env.NECOSMOS_PERF_OUTPUT||'artifacts/phase234/performance-browser.json';
const scenarios=JSON.parse(process.env.NECOSMOS_PERF_CASES||'[[50,32,1,31],[200,32,20,12],[500,32,100,15],[500,64,100,15]]');
for(const [count,n,speed,seconds] of scenarios){
 await page.evaluate(async({count,n,speed})=>{NeCosmos.play(false);await NeCosmos.benchmarkWorld(count,n);await NeCosmos.setSpeed(speed);}, {count,n,speed});await page.waitForTimeout(4000);
 const result=await page.evaluate(async({count,n,speed,seconds})=>{
  const api=NeCosmos;const initialPopulation=api.state().cats.id.length;api.play(true);const start=performance.now(),day=api.status.day;let frames=0;const samples=[];
  await new Promise(resolve=>{const frame=()=>{frames++;samples.push({timing:api.state().performance,render:api.presentation().frameCost,transport:api.presentation().communication});performance.now()-start<seconds*1000?requestAnimationFrame(frame):resolve();};requestAnimationFrame(frame);});
  const elapsed=(performance.now()-start)/1000;const endFraction=api.playback().pendingDays;api.play(false);await api.setSpeed(speed);const endDay=api.status.day;
  const before=await api.hash();await api.save();await api.load();const restored=await api.hash();
  const input=[];for(let k=0;k<5;k++){const t=performance.now();api.cameraTest();await new Promise(requestAnimationFrame);input.push(performance.now()-t);}
  return {count,grid:n,areaFactor:(n/32)**2,speed,initialPopulation,finalPopulation:api.state().cats.id.length,days:endDay-day,elapsed,fps:frames/elapsed,daysPerSecond:(endDay-day)/elapsed,observationDaysPerSecond:speed===.05?(endDay-day+endFraction)/elapsed:undefined,samples:samples.filter((_,k)=>k%30===0),presentation:api.presentation(),heapBytes:performance.memory?.usedJSHeapSize,workerMemory:await api.memory(),inputMs:input,saveRestoreEqual:before===restored,paused:api.playback()};
 },{count,n,speed,seconds});
 Object.assign(result,await memory());assert.ok(result.saveRestoreEqual);assert.equal(result.paused.running,false);out.push(result);fs.writeFileSync(output,JSON.stringify({renderer:'Chromium / SwiftShader, PC emulation',out,fatal},null,2));console.log(count,n,speed,result.fps,result.daysPerSecond);
}
// Render allocation stress is independent of ecosystem; force GC between rounds.
const session=await page.context().newCDPSession(page),churn=[];
for(let round=0;round<(process.env.NECOSMOS_SKIP_CHURN?0:4);round++){
 await page.evaluate(async()=>{for(let k=0;k<100;k++){NeCosmos.renderStress(k%2?50:500);await new Promise(requestAnimationFrame);}});
 await session.send('HeapProfiler.collectGarbage');await page.waitForTimeout(500);
 churn.push(await page.evaluate(()=>({presentation:NeCosmos.presentation(),heapBytes:performance.memory?.usedJSHeapSize})));
}
assert.equal(fatal.length,0);assert.ok(churn.every(r=>r.presentation.live===50&&r.presentation.frameCost.capacity<=512));
if(churn.length)assert.ok(Math.max(...churn.map(r=>r.presentation.frameCost.geometries))-Math.min(...churn.map(r=>r.presentation.frameCost.geometries))<=1);
fs.writeFileSync(output,JSON.stringify({renderer:'Chromium / SwiftShader, PC emulation',out,churn,fatal},null,2));await browser.close();console.log(`PASS: ${out.length} load scenarios, save/pause/switch, bounded GPU allocations`);
