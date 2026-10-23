import {chromium} from 'playwright';
import fs from 'node:fs';
const base=process.env.NECOSMOS_BASE_URL || 'http://127.0.0.1:8080';
const proxy=base.startsWith('http://127.0.0.1')?undefined:{server:process.env.HTTPS_PROXY || process.env.HTTP_PROXY};
const browser=await chromium.launch({proxy,executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const reports=[];
for(const mobile of [false,true]) {
 const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},deviceScaleFactor:1,isMobile:mobile,hasTouch:mobile});
 const page=await context.newPage();const errors=[];page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(base);await page.waitForFunction(()=>window.NeCosmos?.status.ready && window.NeCosmos?.status.day!==undefined,{},{timeout:120000});await page.evaluate(()=>NeCosmos.ready);
 await page.waitForTimeout(1500);
 const result=await page.evaluate(async()=>{
   const api=NeCosmos;api.play(false);
   await api.newWorld({terrain:'hills',climate:'wet',composition:'all8',seed:21001,weatherMode:'normal'});
   const hash0=await api.hash();
   await Promise.all([api.setSpeed(5),api.setSpeed(20),api.setSpeed(.05)]);
   const paused=api.playback();const hash1=await api.hash();
   api.play(true);return {hash0,hash1,paused,version:api.version,initial:api.status};
 });
 await page.waitForTimeout(3000);
 const observed=await page.evaluate(async()=>{
   const playback=NeCosmos.playback(),display=NeCosmos.displayPositions();
   const ecology=await NeCosmos.ecologicalPositions(Math.min(1,playback.pendingDays));
   const error=Math.max(0,...ecology.positions.map(e=>{const d=display.find(d=>d.id===e.id);return d?Math.hypot(d.x-e.x,d.y-e.y):0;}));
   return {status:NeCosmos.status,presentation:NeCosmos.presentation(),playback,coordinateErrorMetres:error};
 });
 await page.screenshot({path:`artifacts/${mobile?'mobile':'desktop'}-observation.png`});
 const fast=await page.evaluate(async()=>{await NeCosmos.setSpeed(100);return NeCosmos.status.day;});
 await page.waitForTimeout(3500);
 const fastResult=await page.evaluate(async()=>{NeCosmos.play(false);const day=NeCosmos.status.day;await NeCosmos.save();const hash=await NeCosmos.hash();await NeCosmos.load();return {day,hash,reloaded:await NeCosmos.hash(),presentation:NeCosmos.presentation(),status:NeCosmos.status};});
 await page.screenshot({path:`artifacts/${mobile?'mobile':'desktop'}-fast.png`});
 await page.reload();await page.waitForFunction(()=>NeCosmos?.status.ready && NeCosmos?.status.day!==undefined,null,{timeout:120000});await page.evaluate(()=>NeCosmos.ready);
 const bootRestored=await page.evaluate(()=>NeCosmos.status);
 await page.locator('[data-speed="5"]').click();await page.waitForFunction(()=>NeCosmos.playback().speed===5 && !NeCosmos.playback().switching);
 const uiMode=await page.evaluate(()=>NeCosmos.playback());
 reports.push({mobile,errors,result,observed,fastStart:fast,fastResult,bootRestored,uiMode});await context.close();
}
await browser.close();fs.writeFileSync('artifacts/browser.json',JSON.stringify(reports,null,2));
for(const r of reports) {if(r.errors.length || r.result.hash0!==r.result.hash1 || r.fastResult.hash!==r.fastResult.reloaded || r.fastResult.day<=r.fastStart || r.result.version!=="0.12.0" || r.result.paused.running || r.observed.coordinateErrorMetres>1e-8 || r.bootRestored.status!=="ready" || r.uiMode.running) throw new Error(JSON.stringify(r));}
console.log(JSON.stringify(reports,null,2));
