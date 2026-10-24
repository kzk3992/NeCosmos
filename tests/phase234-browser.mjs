import {chromium} from 'playwright';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1280,height:800}});const fatal=[];page.on('pageerror',e=>fatal.push(String(e)));
await page.route('**/cats/grass_cat/grass_cat_back.png',route=>route.abort());
await page.goto('http://127.0.0.1:8080/?smoke=stress');await page.waitForFunction(()=>window.NeCosmos?.status.ready&&NeCosmos.status.day!==undefined,null,{timeout:120000});await page.evaluate(()=>NeCosmos.ready);
const report=await page.evaluate(async()=>{
 const api=NeCosmos;api.play(false);await api.newWorld({terrain:'hills',climate:'wet',composition:'all8',seed:21001,weatherMode:'normal'});api.play(false);
 const original=await api.hash();api.cameraTest();
 for(const n of [500,50,200,500,50,200,500,50]){api.renderStress(n);await new Promise(requestAnimationFrame);}
 const cameraAndPoolHash=await api.hash();
 await Promise.all([api.setSpeed(100),api.setSpeed(5),api.setSpeed(.05)]);
 const switchingHash=await api.hash(),paused=api.playback(),presentation=api.presentation();
 // Run the same committed days with the renderer active and after camera changes.
 await api.step(60);const renderedHash=await api.hash();
 await api.newWorld({terrain:'hills',climate:'wet',composition:'all8',seed:21001,weatherMode:'normal'});api.play(false);await api.setSpeed(100);await api.step(60);const alternateHash=await api.hash();
 return {original,cameraAndPoolHash,switchingHash,paused,presentation,renderedHash,alternateHash};
});
assert.equal(fatal.length,0);assert.equal(report.presentation.missingAssets.length,1);assert.equal(report.original,report.cameraAndPoolHash);assert.equal(report.original,report.switchingHash);assert.equal(report.paused.running,false);assert.equal(report.renderedHash,report.alternateHash);
// Exercise a real GLB object, protected placement and removal on the live game.
const object=await page.evaluate(async()=>{
 const api=NeCosmos;api.play(false);const catalog=await (await fetch('/assets/catalog.json')).json();const asset=catalog.objects.find(o=>o.id==='crystal_01');
 const st=api.state();let placed;
 for(let k=0;k<st.unlocked.length;k++){
  if(!st.unlocked[k])continue;const x=(k%st.n+.5)*st.cell_m,y=(Math.floor(k/st.n)+.5)*st.cell_m;
  const check=await api.check(asset.id,x,y);if(check.ok){placed=await api.place(asset.id,x,y);break;}
 }
 if(!placed?.ok)throw Error('no valid object placement');
 await new Promise(r=>setTimeout(r,500));const before=api.kiwi;const count=api.state().objects.length;await api.save();await api.load();const restored=api.state().objects.length;await api.remove(placed.pid);return {count,restored,removed:api.state().objects.length,kiwiPreserved:api.kiwi===before};
});
assert.equal(object.count,1);assert.equal(object.restored,1);assert.equal(object.removed,0);assert.ok(object.kiwiPreserved);report.object=object;
report.activeControls=await page.evaluate(async()=>{
 const api=NeCosmos;await api.benchmarkWorld(500,32);await api.setSpeed(100);api.play(true);await new Promise(r=>setTimeout(r,600));
 const saved=await api.save();await api.setSpeed(20);const resumed=api.playback();api.play(false);await api.setSpeed(1);return {saved,resumed,paused:api.playback(),population:api.state().cats.id.length};
});
assert.ok(report.activeControls.saved);assert.equal(report.activeControls.resumed.running,true);assert.equal(report.activeControls.paused.running,false);assert.equal(fatal.length,0);
await page.screenshot({path:'artifacts/phase234/missing-asset.png'});fs.writeFileSync('artifacts/phase234/browser-edge.json',JSON.stringify({fatal,report},null,2));await browser.close();console.log('PASS: missing-asset fallback, camera/pool invariance, mode barrier, rendered replay');
