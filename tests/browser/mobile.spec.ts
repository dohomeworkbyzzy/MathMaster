import {test,expect} from '@playwright/test';

test.use({viewport:{width:390,height:844}});
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');

test('phone uploads paper answers, preserves desktop draft, resumes and detects concurrent edits',async({page,request})=>{
 const tag='手机作答-'+Date.now();const q=await(await request.post('/api/questions',{data:{number:'1',subject:'数学二',text:tag+' 求 $x^2$ 的导数',confirmed:true}})).json();
 await request.put('/api/questions/'+q.id+'/attempt',{data:{answer:'原答案',notes:'原笔记',draft:'{"strokes":[1]}',status:'作答中',wrong:false}});
 await page.goto('/mobile');await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:/开始练习/}).filter({hasText:tag}).click();
 await expect(page.getByLabel('电子草稿画布')).toHaveCount(0);
 await page.getByLabel('我的答案',{exact:true}).fill('2x');await page.getByLabel('做题笔记',{exact:true}).fill('使用幂函数求导');
 await expect(page.getByLabel('上传作答照片')).toBeEnabled();await page.getByLabel('上传作答照片').setInputFiles({name:'answer.png',mimeType:'image/png',buffer:png});await expect(page.getByAltText('作答照片 1',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'上传做题记录',exact:true}).click();await expect(page.getByRole('heading',{name:'已上传记录 · 1'})).toBeVisible();
 const saved=await(await request.get('/api/questions/'+q.id)).json();expect(saved.attempt.answer).toBe('2x');expect(saved.attempt.draft).toBe('{"strokes":[1]}');
 const records=await(await request.get('/api/grading/questions/'+q.id)).json();expect(records.history[0].images).toHaveLength(1);
 await page.reload();await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:/开始练习/}).filter({hasText:tag}).click();await expect(page.getByLabel('我的答案',{exact:true})).toHaveValue('2x');await expect(page.getByAltText('作答照片 1',{exact:true})).toBeVisible();
 await page.getByLabel('做题笔记',{exact:true}).fill('手机未同步笔记');
 await request.put('/api/questions/'+q.id+'/attempt',{data:{...saved.attempt,updated_at:undefined,notes:'电脑的新笔记'}});
 await page.getByRole('button',{name:'上传做题记录',exact:true}).click();await expect(page.getByRole('alert')).toContainText('其他窗口更新');
 expect((await(await request.get('/api/questions/'+q.id)).json()).attempt.notes).toBe('电脑的新笔记');
 await page.getByRole('button',{name:'保留手机副本，读取网站最新记录',exact:true}).click();
 await expect(page.getByLabel('做题笔记',{exact:true})).toHaveValue('电脑的新笔记');
 await page.getByText('冲突前的手机文字副本（可复制合并）',{exact:true}).click();await expect(page.getByText('手机未同步笔记',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'用此副本填回答案和笔记',exact:true}).click();await page.getByRole('button',{name:'上传做题记录',exact:true}).click();await expect(page.getByRole('heading',{name:'已上传记录 · 2'})).toBeVisible();
 await page.screenshot({path:'artifacts/mobile-practice.png',fullPage:true});
});

test('phone AI dialogue, actual session receipts, recommendation and API profiles',async({page,request})=>{
 const tag='手机AI-'+Date.now();const q=await(await request.post('/api/questions',{data:{number:'2',subject:'数学二',text:tag+' 求 sin(x) 的导数',confirmed:true}})).json();
 const next=await(await request.post('/api/questions',{data:{number:'3',subject:'数学二',text:tag+' 推荐题',confirmed:true}})).json();
 let session:any;
 await page.route('**/api/ai/provider',r=>r.fulfill({json:{configured:true,model_id:'test-model'}}));
 await page.route('**/api/ai/sessions/*/turns',async r=>{const b=r.request().postDataJSON();expect(b.text).toBe('请帮我核对求导公式');expect(b.request_id.length).toBeGreaterThan(20);session={...session,busy:false,version:1,turns:[{id:'mobile-turn',request_id:b.request_id,user_text:b.text,message:'先回忆正弦函数求导规则。',status:'complete',error:''}]};await r.fulfill({status:202,json:session});});
 await page.route('**/api/ai/sessions/*/recommend',async r=>{const info=await(await request.get('/api/questions/'+q.id+'/difficulty')).json();await r.fulfill({json:{question_id:next.id,reason:'巩固相同知识点',current_difficulty:info.rating,target:info.progress}});});
 page.on('response',async r=>{if(r.url().endsWith('/api/questions/'+q.id+'/ai')&&r.ok())session=await r.json();});
 await page.goto('/mobile');await page.getByLabel('搜索题库').fill(tag+' 求');await page.getByRole('button',{name:/开始练习/}).filter({hasText:tag+' 求'}).click();await page.getByRole('button',{name:'AI 解题 / 推荐',exact:true}).click();
 await expect.poll(()=>session?.question_id).toBe(q.id);await page.getByLabel('描述解题思路').fill('请帮我核对求导公式');await page.getByRole('button',{name:'发送给 AI',exact:true}).click();await expect(page.locator('.m-reply')).toContainText('正弦函数');
 await page.getByRole('button',{name:'推荐下一题',exact:true}).click();await expect(page.locator('.difficulty-result')).toContainText('相同知识点');await page.getByRole('button',{name:'开始推荐题 →',exact:true}).click();await expect(page.locator('.m-problem')).toContainText('推荐题');
 await page.getByRole('navigation',{name:'手机导航'}).getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('button',{name:'新增解题配置',exact:true}).click();await page.getByLabel('配置名称',{exact:true}).fill('手机测试配置');await page.getByLabel('接口地址',{exact:true}).fill('https://example.test/v1');await page.getByLabel('模型名称',{exact:true}).fill('test-model');await page.getByLabel('API 密钥',{exact:true}).fill('test-key');await page.getByRole('button',{name:'保存并启用',exact:true}).click();await expect(page.locator('.provider-card.selected')).toContainText('手机测试配置');
 const profile=await(await request.get('/api/ai/profiles')).json();expect(profile.profiles.find((p:any)=>p.id===profile.active_chat).provider_name).toBe('手机测试配置');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'artifacts/mobile-settings.png',fullPage:true});
});
