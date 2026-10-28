import {test,expect,type Page} from '@playwright/test';

test('three users keep separate work and model choices across switching, reload and mobile',async({page,request,browser})=>{
 const tag='USER-'+Date.now(),first='访客甲',second='访客乙';
 const modelA=tag+'-model-a',modelB=tag+'-model-b';
 const q=await(await request.post('/api/questions',{data:{text:tag+' 用户练习题',subject:'数学二',confirmed:true}})).json();
 const models:Record<string,string>={};
 for(const model of [modelA,modelB]){
  const registry=await(await request.post('/api/ai/profiles',{data:{kind:'chat',provider_name:'Hidden website '+model,base_url:'https://hidden-website.invalid/v1',model_id:model,api_key:'hidden-test-key',protocol:'openai_chat_completions'}})).json();
  models[model]=registry.profiles.find((p:any)=>p.model_id===model).id;
 }
 await request.post('/api/ai/profiles/'+models[modelA]+'/activate',{data:{}});
 async function openQuestion(p:Page){
  await p.getByRole('button',{name:'本地题库',exact:true}).click();
  await p.getByLabel('搜索题库').fill(tag);
  await p.locator('.question-card').filter({hasText:tag}).getByRole('button',{name:'开始练习'}).click();
  await expect(p.getByLabel('解题笔记',{exact:true})).toBeVisible();
 }
 async function menu(p:Page){await p.getByRole('button',{name:/选择用户，当前/}).click();await expect(p.getByRole('dialog',{name:'选择用户'})).toBeVisible();}
 async function register(name:string){
  await menu(page);await page.getByLabel('新用户名').fill(name);
  await page.getByRole('button',{name:'注册并进入'}).click();
  await expect(page.getByRole('button',{name:'选择用户，当前 '+name})).toBeVisible();
 }
 async function choose(p:Page,name:string){
  await menu(p);await p.getByRole('button',{name:'选择 '+name,exact:true}).click();
  await expect(p.getByRole('button',{name:'选择用户，当前 '+name})).toBeVisible();
 }
 await page.goto('/');await expect(page.getByRole('button',{name:'选择用户，当前 zzy'})).toBeVisible();
 await openQuestion(page);await page.getByLabel('解题笔记',{exact:true}).fill('zzy 专属笔记');
 await register(first);
 expect((await(await request.get('/api/questions/'+q.id)).json()).attempt.notes).toBe('zzy 专属笔记');
 const firstId=(await(await page.request.get('/api/users')).json()).current_user;
 await page.context().setExtraHTTPHeaders({'X-Forwarded-Host':'external.example'});
 await page.getByRole('button',{name:'API 配置',exact:true}).click();
 const card=page.locator('.provider-card').filter({has:page.getByText(modelB,{exact:true})});
 await card.getByRole('button',{name:'启用',exact:true}).click();await expect(card).toContainText('使用中');
 await expect(page.getByRole('region',{name:'API 可视化配置'})).not.toContainText('hidden-website');
 await openQuestion(page);await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('');
 await page.getByLabel('解题笔记',{exact:true}).fill('访客甲 专属笔记');
 await register(second);
 await openQuestion(page);await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('');
 await page.getByLabel('解题笔记',{exact:true}).fill('访客乙 专属笔记');
 await menu(page);await expect(page.getByText('三个名额已满，可选择已有用户。')).toBeVisible();await expect(page.getByLabel('新用户名')).toHaveCount(0);
 await page.getByRole('button',{name:'选择 '+first,exact:true}).click();
 await expect(page.getByRole('button',{name:'选择用户，当前 '+first})).toBeVisible();
 await openQuestion(page);await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('访客甲 专属笔记');
 expect((await(await page.request.get('/api/ai/provider')).json()).model_id).toBe(modelB);
 await page.reload();await page.getByRole('button',{name:'继续上一道题',exact:true}).click();
 await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('访客甲 专属笔记');
 // A different browser/device can choose the existing user and recover server-side data.
 const device=await browser.newContext({viewport:{width:390,height:844}});const phone=await device.newPage();
 await phone.goto('/mobile');await choose(phone,first);
 expect((await(await phone.request.get('/api/ai/provider')).json()).model_id).toBe(modelB);
 expect((await(await phone.request.get('/api/questions/'+q.id)).json()).attempt.notes).toBe('访客甲 专属笔记');
 await choose(phone,'zzy');
 expect((await(await phone.request.get('/api/ai/provider')).json()).model_id).toBe(modelA);
 expect((await(await phone.request.get('/api/questions/'+q.id)).json()).attempt.notes).toBe('zzy 专属笔记');
 // The first tab remains bound to its user despite the separate browser selection.
 expect((await(await request.get('/api/questions/'+q.id,{headers:{'X-MathMaster-User':firstId}})).json()).attempt.notes).toBe('访客甲 专属笔记');
 await device.close();
});
