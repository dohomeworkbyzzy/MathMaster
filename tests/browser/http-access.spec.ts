import {test,expect} from '@playwright/test';

// Keep the page on a genuine non-secure HTTP origin while forwarding its
// requests locally, so these tests do not depend on DNS or host proxy settings.
test.beforeEach(async({page})=>{
 await page.route('http://master-http.test:8767/**',async route=>{
  const url=new URL(route.request().url());url.hostname='127.0.0.1';
  try{
   const response=await route.fetch({url:url.toString(),headers:{...route.request().headers(),host:'master-http.test:8767'}});
   await route.fulfill({response});
  }catch(error){
   // Navigation and AbortController can cancel a request while it is forwarded.
   if(!/Route is already handled|Target .*closed/.test(String(error)))throw error;
  }
 });
});
test.afterEach(async({page})=>{await page.unrouteAll({behavior:'ignoreErrors'});});

test('public HTTP without randomUUID loads, saves notes, edits rubric and grades an answer',async({page,request})=>{
 const tag='HTTP-'+Date.now();
 const q=await(await request.post('/api/questions',{data:{number:tag,text:'选择题 · 2分\n'+tag+' 以下答案选 A。',subject:'408',reference_answer:'A',confirmed:true}})).json();
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const response=await page.goto('http://master-http.test:8767/');expect(response?.status()).toBe(200);
 await expect(page.getByRole('button',{name:'选择用户，当前 zzy'})).toBeVisible();
 expect(await page.evaluate(()=>({secure:isSecureContext,uuid:typeof crypto.randomUUID,random:typeof crypto.getRandomValues}))).toEqual({secure:false,uuid:'undefined',random:'function'});
 const uuid=await page.evaluate(()=>sessionStorage.getItem('mathmaster-tab-id'));
 expect(uuid).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
 await expect(page.getByRole('button',{name:'选择用户，当前 zzy'})).toBeVisible();
 await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);
 await page.getByRole('button',{name:'开始练习'}).click();
 await page.getByLabel('解题笔记',{exact:true}).fill('Saved over public HTTP');
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await page.getByRole('button',{name:'答案与批改',exact:true}).click();
 await page.getByRole('dialog').locator('details.grading-rules > summary').click();
 await page.getByRole('button',{name:'编辑评分要求',exact:true}).click();
 await page.getByRole('button',{name:'添加评分点',exact:true}).click();
 await expect(page.getByLabel('评分点 1',{exact:true})).toBeVisible();
 await page.getByRole('radio',{name:'A',exact:true}).check();
 const result=page.waitForRequest(r=>r.url().endsWith('/check')&&r.method()==='POST');
 await page.getByRole('button',{name:'核对当前题目'}).click();
 expect((await result).postDataJSON().request_id).toMatch(/^[0-9a-f-]{36}$/);
 await expect(page.getByRole('dialog').locator('.grade-result')).toContainText('已评分 · 2 / 2 分');
 await page.getByRole('button',{name:'关闭答案批改'}).click();
 await page.getByRole('button',{name:'继续做题',exact:true}).click();
 expect((await(await request.get('/api/questions/'+q.id)).json()).attempt.notes).toBe('Saved over public HTTP');
 await page.reload();expect(await page.evaluate(()=>sessionStorage.getItem('mathmaster-tab-id'))).toBe(uuid);
 expect(errors).toEqual([]);
});

test('HTTP whole-paper grading generates a request ID without secure-context APIs',async({page,request})=>{
 const {readFile}=await import('node:fs/promises');
 const p=await(await request.post('/api/papers/import',{multipart:{file:{name:'http.pdf',mimeType:'application/pdf',buffer:await readFile('tests/fixtures/exam.pdf')},subject:'408'}})).json();
 const qs=await(await request.get('/api/questions?paper_id='+p.id)).json();
 for(const q of qs)await request.put('/api/questions/'+q.id,{data:{number:q.number,text:'选择题 · 2分\n以下答案选 A。',subject:'408',reference_answer:'A',confirmed:true}});
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://master-http.test:8767/');await page.getByRole('button',{name:'整卷批改',exact:true}).click();
 await page.getByLabel('整卷试卷').selectOption(p.id);await page.getByRole('button',{name:'新建整卷作答'}).click();
 await page.getByRole('radio',{name:'A',exact:true}).check();
 const submission=page.waitForRequest(r=>r.url().endsWith('/grade')&&r.method()==='POST');
 await page.getByRole('button',{name:'整套试卷批改'}).click();
 expect((await submission).postDataJSON().request_id).toMatch(/^[0-9a-f-]{36}$/);
 await expect(page.locator('.exam-score')).toContainText('总分：2 / 4');
 expect(errors).toEqual([]);
});

test('HTTP AI messages generate and retain request receipts without randomUUID',async({page,request})=>{
 const tag='HTTP-AI-'+Date.now();
 const q=await(await request.post('/api/questions',{data:{text:tag+' 描述当前思路',subject:'数学二',confirmed:true}})).json();
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,model_id:'http-fixture'}}));
 await page.goto('http://master-http.test:8767/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习'}).click();
 const opened=page.waitForResponse(r=>r.url().endsWith('/api/questions/'+q.id+'/ai'));
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();const session=await(await opened).json();
 await page.route('**/api/ai/sessions/*/turns',async route=>{
  const body=route.request().postDataJSON();expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  await route.fulfill({status:202,json:{...session,version:1,busy:false,turns:[{id:'http-receipt',request_id:body.request_id,user_text:body.text,message:'HTTP received',status:'complete',error:''}]}});
 });
 await page.getByLabel('描述解题思路').fill('HTTP request receipt test');
 await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.getByText('HTTP received',{exact:true})).toBeVisible();
 expect(errors).toEqual([]);
});

test('remote visitors pair their own helper and never start the server touchpad',async({page,request})=>{
 const tag='LOCAL-TOUCHPAD-'+Date.now();
 await request.post('/api/questions',{data:{number:tag,text:'访客本机触摸板',confirmed:true}});
 let serverStarts=0,helperStops=0;
 page.on('request',r=>{if(r.url()==='http://master-http.test:8767/api/touchpad/start')serverStarts++;});
 const {readFile}=await import('node:fs/promises');
 const helperHTML=(await readFile('backend/touchpad_connect.py','utf8')).split("r'''")[1].split("'''")[0];
 await page.context().addInitScript(()=>{
  if(location.port!=='18765')return;
  (window as any).__helperStreams=[];
  (window as any).EventSource=class {
   onmessage:any=null;onerror:any=null;url:string;closed=false;
   constructor(url:string){this.url=url;(window as any).__helperStreams.push(this);}
   close(){this.closed=true;}
  };
 });
 await page.context().route('http://127.0.0.1:18765/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/connect')return route.fulfill({contentType:'text/html',body:helperHTML});
  if(url.pathname.endsWith('/start')){
   expect(route.request().postDataJSON()).toEqual({code:'12345678'});
   return route.fulfill({json:{token:'helper-token-1234567890123456',devices:[{x_range:[0,100],y_range:[0,60]}]}});
  }
  if(url.pathname.endsWith('/stop')){helperStops++;return route.fulfill({json:{stopped:true}});}
  await route.abort();
 });
 await page.goto('http://master-http.test:8767/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习'}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'连接本机触控板'})).toBeVisible();
 const download=await request.get('/assets/MathMasterTouchpad.zip');expect(download.ok()).toBeTruthy();expect(download.headers()['content-type']).toContain('application/zip');expect((await download.body()).subarray(0,2).toString()).toBe('PK');
 await page.getByLabel('本机助手配对码').fill('12345678');
 const popupPromise=page.waitForEvent('popup');
 await page.getByRole('button',{name:'连接本机触控板',exact:true}).click();const popup=await popupPromise;
 await expect(page.getByRole('button',{name:'触控板书写',exact:true})).toHaveAttribute('aria-pressed','true');
 expect(serverStarts).toBe(0);
 expect(await popup.evaluate(()=>(window as any).__helperStreams[0].url)).toContain('/api/touchpad/events?token=');
 expect(popup.url()).toBe('http://127.0.0.1:18765/connect');
 // Feed a normalized hardware stroke through the helper stream and commit it
 // with a hardware mouse move, then verify the normal question autosave.
 const hardwareMouse=await page.evaluate(()=>{
  const paper=document.querySelector('canvas[aria-label="电子草稿画布"]')!.getBoundingClientRect();
  return {screen_x:window.screenX+paper.left+paper.width/2,screen_y:window.screenY+(window.outerHeight-window.innerHeight)+paper.top+40};
 });
 await popup.evaluate(mouse=>{(window as any).__helperStreams[0].onmessage({data:JSON.stringify({type:'mouse',...mouse})});},hardwareMouse);
 await expect(page.getByLabel('草稿落笔范围')).toBeVisible();
 await popup.evaluate(mouse=>{
  const send=(event:any)=>(window as any).__helperStreams[0].onmessage({data:JSON.stringify(event)});
  send({type:'contact',down:true,id:1,x:.2,y:.2});send({type:'contact',down:true,id:1,x:.8,y:.8});send({type:'contact',down:false});
 },hardwareMouse);
 await expect(page.getByLabel('放大笔迹').locator('path')).toHaveCount(2);
 await popup.evaluate(mouse=>{(window as any).__helperStreams[0].onmessage({data:JSON.stringify({type:'mouse',...mouse,screen_x:mouse.screen_x+10})});},hardwareMouse);
 await expect.poll(async()=>{
  const qs=await (await request.get('/api/questions?search='+encodeURIComponent(tag))).json();
  const question=await (await request.get('/api/questions/'+qs.find((q:any)=>q.number===tag).id)).json();
  return JSON.parse(question.attempt?.draft||'[]').length;
 }).toBe(1);
 await page.getByRole('button',{name:'完成',exact:true}).click();
 await expect.poll(()=>helperStops).toBe(1);
 await expect.poll(()=>popup.isClosed()).toBe(true);
});
