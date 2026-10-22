import {chromium} from 'playwright';import fs from 'node:fs';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:900,height:700}});await page.goto('http://127.0.0.1:8080');await page.evaluate(()=>new Promise(resolve=>{const id=setInterval(()=>{if(window.NeCosmos?.status.ready&&NeCosmos.status.day!==undefined){clearInterval(id);resolve();}},50);}));await page.evaluate(()=>NeCosmos.ready);
const out=[];
for(const speed of [.05,1,5,10,20,100]){
 await page.evaluate(async speed=>{NeCosmos.play(false);await NeCosmos.newWorld({terrain:'hills',climate:'wet',composition:'all8',weatherMode:'normal',seed:21001});await NeCosmos.setSpeed(speed);},speed);
 const timing=await page.evaluate(async speed=>{
  const day=NeCosmos.status.day,start=performance.now();NeCosmos.play(true);
  await new Promise(resolve=>{const id=setInterval(()=>{if(NeCosmos.status.day>=day+1){clearInterval(id);resolve();}},10);});
  const elapsed=(performance.now()-start)/1000;NeCosmos.play(false);
  await NeCosmos.setSpeed(speed); // drain any in-flight transaction and preserve pause
  return {speed,secondsPerDay:elapsed,day:NeCosmos.status.day,fps:NeCosmos.presentation().fps,hash:await NeCosmos.hash()};
 },speed);out.push(timing);fs.writeFileSync('artifacts/realtime.json',JSON.stringify(out,null,2));console.log(timing);
}
await browser.close();
if(new Set(out.map(r=>r.hash)).size!==1)throw new Error('speed-dependent state');
