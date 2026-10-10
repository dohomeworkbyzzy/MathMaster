// Record real UI + real local calculations in an isolated demo database.
// Touchpad frames use explicit synthetic contacts, visibly labelled as a diagram.
// This does not claim a physical finger/device recording and never modifies production input.
import {chromium} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const base=process.env.MATHMASTER_DEMO_URL||'http://127.0.0.1:8768';
if(!/^http:\/\/127\.0\.0\.1:876[78]$/.test(base))throw Error('Use an isolated demo service on 8767/8768.');
const portable=resolve('.tools/tesseract/usr/lib/x86_64-linux-gnu');
const browser=await chromium.launch({headless:true,env:{...process.env,LD_LIBRARY_PATH:process.env.LD_LIBRARY_PATH||portable}});
const page=await browser.newPage({viewport:{width:1200,height:800}});
await page.route('**/*',r=>r.request().url().startsWith(base)||r.request().url().startsWith('data:')?r.continue():r.abort());
const groups={calculator:[],trackpad:[]};
let group='calculator';

async function overlay(){
 await page.evaluate(()=>{
  const el=document.createElement('div');el.id='demo-caption';el.style.cssText='position:fixed;bottom:12px;left:12px;max-width:720px;background:#103c36;color:white;padding:10px 18px;border-radius:6px;font:16px sans-serif;z-index:10000;pointer-events:none';document.body.append(el);
 });
}
async function caption(text){await page.locator('#demo-caption').evaluate((el,t)=>el.textContent=t,text);}
async function shot(duration=150){
 const path=`artifacts/demo-frames/${group}/${String(groups[group].length).padStart(3,'0')}.png`;
 await page.screenshot({path});groups[group].push({path,duration});
}
async function stage(text,duration=1500){await caption(text);await shot(duration);}

try{
 mkdirSync('artifacts/demo-frames/calculator',{recursive:true});mkdirSync('artifacts/demo-frames/trackpad',{recursive:true});
 await page.goto(base);await page.locator('h1').waitFor();await overlay();
 await stage('积分：本地计算精确答案与中文推导');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await page.locator('.verified-badge').waitFor();assert.equal(await page.locator('.verified-badge').innerText(),'验证通过');
 await stage('分部积分：结果带积分常数 C，并独立求导验证',2200);
 await page.locator('.step').first().scrollIntoViewIfNeeded();await stage('每一步展示所用公式、变形过程和验证状态',2300);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.getByRole('button',{name:'求导',exact:true}).click();await page.getByRole('button',{name:'文本表达式',exact:true}).click();
 await page.getByLabel('文本表达式',{exact:true}).fill('sin(x^2)');await stage('求导：输入 sin(x²)，查看链式法则');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();await page.locator('.verified-badge').waitFor();
 await stage('精确结果 2x·cos(x²)，推导由本地 SymPy 验证',2200);
 await page.getByRole('button',{name:'矩阵',exact:true}).click();await page.getByLabel('矩阵运算方式').selectOption('inverse');
 await stage('矩阵：表格输入，选择逆矩阵');await page.getByRole('button',{name:'开始计算',exact:true}).click();await page.locator('.verified-badge').waitFor();
 await stage('通过增广矩阵行变换求逆，展示每一次初等行操作',2500);
 await page.locator('.step').first().scrollIntoViewIfNeeded();await stage('每次行变换记录前后矩阵，结果交叉验证',2200);

 group='trackpad';
 await page.addInitScript(()=>{
  class DiagramStream{constructor(){window.__demoPad=this;}close(){}}
  window.EventSource=DiagramStream;
 });
 await page.route('**/api/touchpad/start',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({token:'diagram-only-contact-token-123456',devices:[{x_range:[0,3684],y_range:[0,2176],aspect_ratio:457/281}]})}));
 await page.route('**/api/touchpad/stop',r=>r.fulfill({contentType:'application/json',body:'{"stopped":true}'}));
 const response=await page.request.post(base+'/api/questions',{data:{text:'计算 $\\int x e^x dx$，在草稿区记录中间运算。',number:'触控板示例',subject:'数学一',confirmed:true}});
 const q=await response.json();assert(response.ok());
 await page.goto(base);await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill('触控板示例');
 await page.locator('.question-card').first().getByRole('button',{name:/开始练习|继续作答/}).click();await overlay();
 await page.evaluate(()=>{
  const panel=document.createElement('div');panel.id='demo-pad';panel.style.cssText='position:fixed;right:18px;bottom:70px;width:270px;padding:14px;background:white;border:1px solid #aaa;border-radius:10px;z-index:10000;pointer-events:none;font:13px sans-serif';
  panel.innerHTML='<b>笔记本触控板 · 操作示意</b><div style="position:relative;margin:12px 0;height:135px;border:2px solid #777;border-radius:8px;background:#f4f4f4"><span id="demo-finger" style="position:absolute;display:none;width:20px;height:20px;background:#d7805b;border-radius:50%;transform:translate(-50%,-50%)"></span></div><small>合成触点驱动实际界面，非实机手指录制</small>';document.body.append(panel);
  const cursor=document.createElement('span');cursor.id='demo-cursor';cursor.style.cssText='position:fixed;width:14px;height:14px;border:2px solid #28714f;border-radius:50%;transform:translate(-50%,-50%);z-index:9999;pointer-events:none';document.body.append(cursor);
 });
 await stage('1. 开启触控板书写，用外接鼠标定位落笔中心',2200);
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();await page.getByRole('dialog',{name:'触控板放大书写区'}).waitFor();
 const canvas=page.getByLabel('电子草稿画布');const box=await canvas.boundingBox();
 await page.locator('#demo-cursor').evaluate((el,b)=>{el.style.left=(b.x+b.width*.2)+'px';el.style.top=(b.y+b.width*.1125)+'px';},box);
 await stage('2. 单指书写；触控板坐标映射到放大区域，光标保持落笔位置',1800);
 const emit=async events=>page.evaluate(events=>{for(const e of events)window.__demoPad.onmessage({data:JSON.stringify(e)});},events);
 const strokes=[[[.15,.34],[.29,.66]],[[.15,.66],[.29,.34]],[[.33,.28],[.36,.22],[.4,.22],[.43,.26],[.41,.3],[.35,.35],[.43,.35]],[[.49,.5],[.64,.5]],[[.565,.36],[.565,.64]],[[.73,.4],[.79,.34],[.79,.66]],[[.74,.66],[.84,.66]]];
 function interpolate(line){return line.flatMap((p,i)=>i===0?[p]:Array.from({length:6},(_,k)=>[line[i-1][0]+(p[0]-line[i-1][0])*(k+1)/6,line[i-1][1]+(p[1]-line[i-1][1])*(k+1)/6]));}
 let id=0;
 for(const line of strokes){
  const points=interpolate(line);id++;
  for(let i=0;i<points.length;i+=3){
   const batch=points.slice(i,i+3);await emit(batch.map(([x,y])=>({type:'contact',down:true,id,x,y})));
   const [x,y]=batch.at(-1);await page.locator('#demo-finger').evaluate((el,p)=>{el.style.display='block';el.style.left=(p[0]*100)+'%';el.style.top=(p[1]*100)+'%';},[x,y]);
   await shot(100);
  }
  await emit([{type:'contact',down:false}]);await page.locator('#demo-finger').evaluate(el=>el.style.display='none');await shot(180);
 }
 await stage('3. 抬指结束一笔，笔画保留在同一放大区域',1800);
 assert.equal(await page.getByLabel('放大笔迹').locator('path:not(.touchpad-center)').count(),strokes.length);
 const destination=await canvas.evaluate(el=>{const b=el.getBoundingClientRect();return {type:'mouse',screen_x:window.screenX+b.left+b.width*.7,screen_y:window.screenY+window.outerHeight-window.innerHeight+b.top+b.width*.32};});
 await caption('4. 移动外接鼠标，整组字迹自动缩小并收进草稿');await emit([destination]);
 for(let i=0;i<4;i++){await shot(80);await page.waitForTimeout(60);}
 await page.locator('#demo-cursor').evaluate((el,b)=>{el.style.left=(b.x+b.width*.7)+'px';el.style.top=(b.y+b.width*.32)+'px';},box);
 await stage('已收笔：字迹保存在草稿；鼠标的新位置用于下一组',1800);
 await page.getByLabel('书写区大小').fill('260');await stage('5. 手动调小书写区，260px；收笔尺寸可以单独设置',2400);
 await emit([{type:'contact',down:true,id:20,x:.25,y:.4},{type:'contact',down:true,id:20,x:.75,y:.4},{type:'contact',down:false}]);
 await stage('小书写区也能继续运算；Esc 收笔并退出',1800);await page.keyboard.press('Escape');
 await page.getByLabel('解题笔记',{exact:true}).fill('分部积分：令 u=x，dv=e^x dx。');
 await page.waitForTimeout(1100);await stage('6. 草稿和笔记自动保存，可以继续作答',2500);
 const saved=await (await page.request.get(base+'/api/questions/'+q.id)).json();assert.equal(JSON.parse(saved.attempt.draft).length,strokes.length+1);
 writeFileSync('artifacts/demo-frames/frames.json',JSON.stringify(groups,null,2));
 console.log('Real calculations and saved diagram strokes verified; frames recorded.');
}finally{await browser.close();}
