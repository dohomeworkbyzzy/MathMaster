import {test,expect} from '@playwright/test';

test('external API settings allow switching without exposing provider details',async({page,request,context})=>{
 const tag='external-model-'+Date.now();
 const initial=await (await request.post('/api/ai/profiles',{data:{kind:'chat',provider_name:'Initial hidden provider',base_url:'https://initial-hidden.invalid/v1',model_id:tag+'-initial',api_key:'initial-hidden-key',protocol:'openai_chat_completions'}})).json();
 await request.post('/api/ai/profiles/'+initial.profiles.find((p:any)=>p.model_id===tag+'-initial').id+'/activate',{data:{}});
 await request.post('/api/ai/profiles',{data:{kind:'chat',provider_name:'Hidden provider',base_url:'https://hidden.invalid/v1',model_id:tag,api_key:'hidden-key',protocol:'openai_chat_completions'}});
 await context.setExtraHTTPHeaders({'X-Forwarded-Host':'external.example'});
 const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/ai/profiles'));
 await page.goto('/');await page.getByRole('button',{name:'API 配置',exact:true}).click();
 const response=await responsePromise;const registry=await response.json();
 expect(registry.read_only).toBe(true);
 for(const p of registry.profiles)expect(Object.keys(p).sort()).toEqual(['id','kind','model_id']);
 const board=page.getByRole('region',{name:'API 可视化配置'});
 await expect(board).toContainText(tag);await expect(board).toContainText('外网访问仅显示模型名称');
 const card=board.locator('.provider-card').filter({has:page.getByText(tag,{exact:true})});
 const activate=page.waitForResponse(r=>r.url().endsWith('/activate')&&r.request().method()==='POST');
 await card.getByRole('button',{name:'启用',exact:true}).click();
 const switched=await (await activate).json();
 expect(switched.active_chat).toBe(registry.profiles.find((p:any)=>p.model_id===tag).id);
 for(const p of switched.profiles)expect(Object.keys(p).sort()).toEqual(['id','kind','model_id']);
 expect(JSON.stringify(switched)).not.toContain('hidden.invalid');
 await expect(card).toContainText('使用中');
 await expect(board.getByRole('button',{name:/编辑|测试|删除|新增/})).toHaveCount(0);
 await page.reload();await page.getByRole('button',{name:'API 配置',exact:true}).click();
 await expect(board.locator('.provider-card').filter({has:page.getByText(tag,{exact:true})})).toContainText('使用中');
 await expect(board.locator('input,select,textarea,.provider-url,.vector-status')).toHaveCount(0);
 await expect(board).not.toContainText('Hidden provider');await expect(board).not.toContainText('hidden.invalid');
});

test('visual profiles save secrets only in backend and independently switch chat protocols',async({page,request})=>{
 const tag='API配置-'+Date.now();
 await page.goto('/');await page.getByRole('button',{name:'API 配置',exact:true}).click();
 await expect(page.getByRole('region',{name:'API 可视化配置'})).toBeVisible();
 await page.getByRole('button',{name:'新增解题配置'}).click();
 await page.getByLabel('配置名称',{exact:true}).fill(tag);
 await page.getByLabel('接口地址',{exact:true}).fill('https://fixture.invalid/v1');
 await page.getByLabel('模型名称',{exact:true}).fill('fixture-chat');
 await page.getByLabel('API 密钥',{exact:true}).fill('browser-secret-fixture');
 await page.getByLabel('配置思考强度').selectOption('high');
 await page.getByRole('button',{name:'保存并启用',exact:true}).click();
 const card=page.locator('.provider-card').filter({has:page.getByText(tag,{exact:true})});await expect(card).toContainText('使用中');
 let registry=await (await request.get('/api/ai/profiles')).json();const embedding=registry.active_embedding;
 expect(registry.profiles.find((p:any)=>p.id===registry.active_chat).reasoning_effort).toBe('high');
 await expect(card).toContainText('思考强度：高');
 expect(JSON.stringify(registry)).not.toContain('browser-secret-fixture');
 await card.getByRole('button',{name:'编辑',exact:true}).click();await expect(page.getByLabel('API 密钥',{exact:true})).toHaveValue('');
 await page.getByLabel('模型名称',{exact:true}).fill('fixture-chat-updated');await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await expect(card).toContainText('fixture-chat-updated');
 await page.getByRole('button',{name:'新增解题配置'}).click();await page.getByLabel('供应商预设').selectOption('anthropic');
 await expect(page.getByLabel('API 协议')).toHaveValue('anthropic_messages');
 await page.getByLabel('配置名称',{exact:true}).fill(tag+'-Claude');await page.getByLabel('模型名称',{exact:true}).fill('fixture-claude');
 await page.getByLabel('API 密钥',{exact:true}).fill('second-private-key');await page.getByRole('button',{name:'保存并启用',exact:true}).click();
 await expect(page.locator('.provider-card').filter({hasText:tag+'-Claude'})).toContainText('使用中');
 await card.getByRole('button',{name:'启用',exact:true}).click();await expect(card).toContainText('使用中');
 const current=await (await request.get('/api/ai/provider')).json();expect(current.model_id).toBe('fixture-chat-updated');expect(current.protocol).toBe('openai_chat_completions');
 registry=await (await request.get('/api/ai/profiles')).json();expect(registry.active_embedding).toBe(embedding);
 await page.getByRole('button',{name:'知识向量 / Embedding',exact:true}).click();
 await expect(page.getByText('新试卷自动预解析并建立知识向量',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'新增向量配置'}).click();await expect(page.getByLabel('API 协议').locator('option')).toHaveCount(1);
 await expect(page.getByLabel('API 协议')).toHaveValue('openai_embeddings');
 await page.setViewportSize({width:780,height:700});await expect(page.getByLabel('API 密钥',{exact:true})).toBeVisible();
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('private-key');
});

test('reasoning can be changed directly in the tutor and follows the active profile',async({page,request})=>{
 const tag='思考强度-'+Date.now();
 const registry=await (await request.post('/api/ai/profiles',{data:{kind:'chat',provider_name:tag,base_url:'https://fixture.invalid/v1',
   model_id:'glm-5.3',api_key:'reasoning-private-key',protocol:'openai_chat_completions'}})).json();
 const pid=registry.profiles.find((p:any)=>p.provider_name===tag).id;
 await request.post('/api/ai/profiles/'+pid+'/activate',{data:{}});
 const q=await (await request.post('/api/questions',{data:{number:tag,text:tag+' 求导测试',subject:'数学二',confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 const control=page.getByLabel('思考强度',{exact:true});
 await expect(control.locator('option')).toHaveText(['默认','低','高','最高']);
 await control.selectOption('low');await expect(control).toBeEnabled();
 await expect.poll(async()=>(await (await request.get('/api/ai/provider')).json()).reasoning_effort).toBe('low');
 await page.getByRole('button',{name:'收起 AI 解题'}).click();await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect(control).toHaveValue('low');
 await page.setViewportSize({width:780,height:700});await expect(control).toBeVisible();
 const bounds=(await control.boundingBox())!;expect(bounds.x+bounds.width).toBeLessThanOrEqual(780);
 expect(JSON.stringify(await (await request.get('/api/ai/profiles')).json())).not.toContain('reasoning-private-key');
 expect((await (await request.get('/api/questions/'+q.id)).json()).attempt?.answer||'').toBe('');
});

test('knowledge direction search shows real bank links and opens selected practice',async({page,request})=>{
 const tag='向量检索-'+Date.now();const q=await (await request.post('/api/questions',{data:{number:tag,text:'求极限，使用泰勒展开',subject:'数学二',confirmed:true}})).json();
 await page.route('**/api/ai/similar?*',async route=>{
  const url=new URL(route.request().url());expect(url.searchParams.get('text')).toBe('等价无穷小与泰勒展开');expect(url.searchParams.get('subject')).toBe('数学二');
  await route.fulfill({json:{items:[{question_id:q.id,number:tag,paper_title:'本地题目',subject:'数学二',topic:'等价无穷小与泰勒展开',score:.83,reason:'相同的考察方向与展开阶数'}],reason:'按知识方向检索'}});
 });
 await page.goto('/');await page.getByRole('button',{name:'相似题',exact:true}).click();
 await page.getByLabel('检索知识方向').fill('等价无穷小与泰勒展开');await page.getByRole('button',{name:'查找相似题',exact:true}).click();
 await expect(page.locator('.vector-matches')).toContainText('相同的考察方向');
 await page.getByRole('button',{name:'开始练习',exact:true}).click();await expect(page.getByRole('region',{name:'题目区'})).toContainText('泰勒展开');
});
