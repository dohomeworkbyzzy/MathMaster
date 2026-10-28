import {test,expect,type Page,type APIRequestContext} from '@playwright/test';

async function open(page:Page,request:APIRequestContext){
 const tag='发送反馈-'+Date.now();
 const q=await (await request.post('/api/questions',{data:{number:tag,text:tag+' 求 sin(x) 的导数',subject:'数学二',confirmed:true}})).json();
 let session:any;
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,base_url:'https://api.deepseek.com',model_id:'deepseek-flash'}}));
 page.on('response',async r=>{if(r.url().endsWith('/api/questions/'+q.id+'/ai')&&r.ok())session=await r.json();});
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect.poll(()=>session?.id).toBeTruthy();
 return {session,q};
}
function complete(session:any,body:any){
 return {...session,version:session.version+1,busy:false,turns:[{id:'receipt',request_id:body.request_id,user_text:body.text,status:'complete',error:'',message:'结果已保存：导数为 cos(x)。',progress:{phase:'complete',label:'回复已完成并保存'}}]};
}

test('shows live progress, survives polling failures, and double Enter sends once',async({page,request})=>{
 const {session}=await open(page,request);let remote=session,body:any,posts=0,reads=0,finish=false;
 await page.route('**/api/ai/sessions/*/turns',async route=>{
  posts++;body=route.request().postDataJSON();
  remote={...session,busy:true,turns:[{id:'receipt',request_id:body.request_id,user_text:body.text,status:'running',error:'',message:'',created_at:new Date().toISOString(),progress:{phase:'model',label:'正在等待模型回复（第 1 次）'}}]};
  await route.fulfill({status:202,json:remote});
 });
 await page.route('**/api/ai/sessions/*',async route=>{
  reads++;if(reads<=2){await route.abort('connectionfailed');return;}
  await route.fulfill({json:finish?complete(session,body):remote});
 });
 await page.getByLabel('描述解题思路').fill('帮我求导');
 await page.getByLabel('描述解题思路').evaluate(el=>{for(let i=0;i<2;i++)el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));});
 await expect(page.locator('.ai-request-status')).toContainText('正在等待模型回复');
 await expect(page.locator('.ai-request-status')).toContainText('已等待');
 await expect(page.getByRole('alert')).toContainText('暂时无法读取后台结果');
 await expect(page.locator('.ai-request-status')).toContainText('正在等待模型回复');
 finish=true;await page.getByRole('button',{name:'刷新结果',exact:true}).click();
 await expect(page.locator('.ai-response')).toContainText('结果已保存');
 await expect(page.locator('.ai-request-status')).toContainText('回复已完成并保存');
 await expect(page.getByLabel('描述解题思路')).toHaveValue('');expect(posts).toBe(1);
});

test('a lost submission response is recovered from the receipt without another model call',async({page,request})=>{
 const {session,q}=await open(page,request);let remote=session,posts=0;
 await page.route('**/api/ai/sessions/*/turns',async route=>{posts++;remote=complete(session,route.request().postDataJSON());await route.abort('connectionfailed');});
 await page.route('**/api/ai/sessions/*',route=>route.fulfill({json:remote}));
 await page.getByLabel('描述解题思路').fill('帮我求导');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.ai-response')).toContainText('结果已保存');
 await expect(page.getByLabel('描述解题思路')).toHaveValue('');
 expect(await page.evaluate(id=>localStorage.getItem('mathmaster-ai-pending-'+id),q.id)).toBeNull();
 await page.getByRole('button',{name:'刷新结果',exact:true}).click();expect(posts).toBe(1);
});

test('an unconfirmed send survives reopening and a verified retry reuses its request ID',async({page,request})=>{
 const {session,q}=await open(page,request);let remote=session;const ids:string[]=[];
 await page.route('**/api/ai/sessions/*/turns',async route=>{
  const body=route.request().postDataJSON();ids.push(body.request_id);
  if(ids.length===1){await route.abort('connectionfailed');return;}
  remote=complete(session,body);await route.fulfill({status:202,json:remote});
 });
 await page.route('**/api/ai/sessions/*',route=>route.fulfill({json:remote}));
 await page.getByLabel('描述解题思路').fill('帮我求导');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.ai-request-status')).toContainText('发送结果待确认');
 await expect(page.getByLabel('描述解题思路')).toHaveValue('帮我求导');
 await page.getByRole('button',{name:'收起 AI 解题'}).click();await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect(page.getByRole('button',{name:'核对并重试发送',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'核对并重试发送',exact:true}).click();
 await expect(page.locator('.ai-response')).toContainText('结果已保存');
 expect(ids).toHaveLength(2);expect(ids[1]).toBe(ids[0]);
 expect(await page.evaluate(id=>localStorage.getItem('mathmaster-ai-pending-'+id),q.id)).toBeNull();
});
