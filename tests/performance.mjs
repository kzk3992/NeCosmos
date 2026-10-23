import {chromium} from 'playwright';import fs from 'node:fs';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const cdp=await browser.newBrowserCDPSession();
async function processMemory(){
 const {processInfo}=await cdp.send('SystemInfo.getProcessInfo');let pss=0,rss=0;const processes=[];
 for(const p of processInfo){const rollup=fs.readFileSync(`/proc/${p.id}/smaps_rollup`,'utf8');const kb=key=>Number(rollup.match(new RegExp('^'+key+':\\s+(\\d+)','m'))[1])*1024;const v={type:p.type,pssBytes:kb('Pss'),rssBytes:kb('Rss')};processes.push(v);pss+=v.pssBytes;rss+=v.rssBytes;}
 return {totalPssBytes:pss,totalRssBytes:rss,processes};
}
const page=await browser.newPage({viewport:{width:1280,height:800}});await page.goto('http://127.0.0.1:8080/?smoke=stress');await page.waitForFunction(()=>NeCosmos?.status.ready&&NeCosmos?.status.day!==undefined,null,{timeout:120000});await page.evaluate(()=>NeCosmos.ready);
await page.evaluate(async()=>{await NeCosmos.newWorld({terrain:'hills',climate:'wet',composition:'all8',weatherMode:'normal',seed:21001});await NeCosmos.step(500);});
const out=[];
for(const population of [200,500]){
 await page.evaluate(n=>{NeCosmos.play(false);NeCosmos.renderStress(n);},population);await page.waitForTimeout(5000);
 const result=await page.evaluate(async population=>{
  const start=performance.now();let frames=0;await new Promise(resolve=>{const frame=()=>{frames++;performance.now()-start<3000?requestAnimationFrame(frame):resolve();};requestAnimationFrame(frame);});
  const fps=frames/((performance.now()-start)/1000);
  const latency=[];
  for(let i=0;i<5;i++){const t=performance.now();document.getElementById('playBtn').click();NeCosmos.play(false);await new Promise(requestAnimationFrame);latency.push(performance.now()-t);}
  return {population,syntheticRender:true,fps,presentation:NeCosmos.presentation(),mainThreadHeapBytes:performance.memory?.usedJSHeapSize,workerMemory:await NeCosmos.memory(),activationToNextFrameMs:latency,workerLastStep:NeCosmos.state().performance};
 },population);result.browserProcessMemory=await processMemory();out.push(result);
}
await page.evaluate(async()=>{await NeCosmos.setSpeed(100);NeCosmos.play(true);});const start=await page.evaluate(()=>({time:performance.now(),day:NeCosmos.status.day}));await page.waitForTimeout(6000);
const effective=await page.evaluate(start=>{NeCosmos.play(false);return {daysPerSecond:(NeCosmos.status.day-start.day)/((performance.now()-start.time)/1000),lastStep:NeCosmos.state().performance};},start);
fs.writeFileSync('artifacts/performance-browser.json',JSON.stringify({renderer:'Chromium software SwiftShader',out,effective},null,2));await browser.close();console.log(JSON.stringify({out,effective},null,2));
