import {test,expect as baseExpect} from '@playwright/test';
const expect=baseExpect.configure({timeout:20000});

test('offline mathfield, integral, derivative, matrix and history',async({page,request})=>{
 const previousHistory=(await (await request.get('/api/math/history?workspace=true&limit=30')).json()).length;
 const external:string[]=[];const errors:string[]=[];
 await page.route('**/*',route=>{if(!route.request().url().startsWith('http://127.0.0.1:8767')&&!route.request().url().startsWith('data:')){external.push(route.request().url());return route.abort();}return route.continue();});
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await expect(page.getByRole('heading',{name:'数学计算工作台'})).toBeVisible();
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await expect(page.locator('.answer-box')).toContainText('C');await expect(page.locator('.verified-badge')).toHaveText('验证通过');
 await expect(page.locator('.step summary').filter({hasText:'分部积分'}).first()).toBeVisible();
 await page.getByRole('button',{name:'数学虚拟键盘',exact:true}).click();await expect(page.locator('.ML__keyboard')).toBeVisible();await page.locator('h1').click();
 await page.getByRole('button',{name:'求导',exact:true}).click();await page.getByRole('button',{name:'文本表达式',exact:true}).click();await page.getByLabel('文本表达式',{exact:true}).fill('sin(x^2)');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();await expect(page.locator('.answer-box')).toContainText('cos');await expect(page.locator('.step summary').filter({hasText:'链式法则'})).toBeVisible();
 await page.getByRole('button',{name:'矩阵',exact:true}).click();await page.getByLabel('矩阵运算方式').selectOption('inverse');await page.getByRole('button',{name:'开始计算',exact:true}).click();await expect(page.locator('.answer-box')).toContainText('2');await expect(page.locator('.step summary').filter({hasText:'逆矩阵验证'})).toBeVisible();
 await page.getByRole('button',{name:'计算历史',exact:true}).click();await expect(page.locator('.history-item')).toHaveCount(Math.min(30,previousHistory+3));
 await page.screenshot({path:'docs/workspace-history.png',fullPage:true});
 expect(external).toEqual([]);expect(errors).toEqual([]);
});

test('question notes, scratch, calculation insertion and resume',async({page,request})=>{
 const q=await request.post('/api/questions',{data:{text:'计算 $\\int x e^x dx$，写出分部积分过程。',number:'E2E-'+Date.now(),subject:'数学一',confirmed:true}});const {id}=await q.json();
 const next=await request.post('/api/questions',{data:{text:'求 $\\frac{d}{dx}\\sin(x^2)$。',number:'E2E-next-'+Date.now(),subject:'数学二',confirmed:true}});const {id:nextId}=await next.json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill('E2E-');await expect(page.locator('.question-card')).toHaveCount(2);
 await page.locator('.question-card').filter({hasText:'分部积分过程'}).getByRole('button',{name:'开始练习'}).click();await expect(page.getByLabel('解题笔记',{exact:true})).toBeVisible();
 await page.getByLabel('我的答案').fill('(x-1)e^x+C');await page.getByLabel('解题笔记',{exact:true}).fill('令 u=x，dv=e^x dx。');
 const canvas=page.getByLabel('电子草稿画布');const box=(await canvas.boundingBox())!;await page.mouse.move(box.x+30,box.y+35);await page.mouse.down();await page.mouse.move(box.x+80,box.y+55,{steps:8});await page.mouse.up();
 await page.getByRole('button',{name:'开始计算',exact:true}).click();await expect(page.locator('.calc-result-panel .verified-badge')).toHaveText('验证通过');await page.getByRole('button',{name:'插入解题笔记'}).click();await expect(page.locator('.note-calculations')).toContainText('分部积分');
 await page.getByRole('button',{name:'独立浮动',exact:true}).click();await expect(page.locator('.floating-calc')).toBeVisible();await page.getByRole('button',{name:'返回工作台'}).click();
 await page.getByRole('button',{name:'全屏',exact:true}).click();await expect(page.locator('.fullscreen-calc')).toBeVisible();await page.getByRole('button',{name:'返回工作台'}).click();
 await page.getByRole('button',{name:'收起计算器',exact:true}).click();await page.getByRole('button',{name:'展开计算器'}).click();
 await page.getByRole('button',{name:'加入错题本',exact:true}).click();await page.getByRole('button',{name:'完成本题',exact:true}).click();
 await expect(page.locator('.save-status')).toContainText('已保存');
 await page.screenshot({path:'docs/practice-preview.png',fullPage:true});
 await page.getByRole('button',{name:'返回题库'}).click();await page.locator('.question-card').filter({hasText:'分部积分过程'}).getByRole('button',{name:'开始练习'}).click();
 await expect(page.getByLabel('我的答案')).toHaveValue('(x-1)e^x+C');await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('令 u=x，dv=e^x dx。');
 await expect(page.locator('.note-calculations')).toBeVisible();const state=await (await request.get('/api/questions/'+id)).json();expect(JSON.parse(state.attempt.draft).length).toBe(1);
 // A calculation cannot attach to a different question.
 const h=await (await request.get('/api/math/history?question_id='+id)).json();expect((await request.post('/api/questions/'+nextId+'/calculations/'+h[0].id,{data:{}})).status()).toBe(409);
});

test('expression selection requires user confirmation',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.locator('.question-card').filter({hasText:'分部积分过程'}).getByRole('button',{name:'开始练习'}).click();
 await page.getByRole('button',{name:'选中表达式发送到计算器'}).click();await expect(page.getByRole('heading',{name:'确认数学表达式'})).toBeVisible();await page.getByLabel('确认数学表达式',{exact:true}).fill('2x/(x^2+1)');await page.getByRole('button',{name:'确认并填入计算器'}).click();await page.getByRole('button',{name:'开始计算',exact:true}).click();await expect(page.locator('.calc-result-panel .answer-box')).toContainText('log');
});

test('real PDF upload, review and question practice',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'导入试卷',exact:true}).click();await page.getByLabel('上传试卷').setInputFiles('tests/fixtures/exam.pdf');await page.getByLabel('试卷名称',{exact:true}).fill('浏览器导入验收试卷');
 await page.getByRole('button',{name:'导入并自动拆题'}).click();await expect(page.locator('.import-result')).toContainText('共 2 道待检查题目');await page.getByRole('button',{name:'检查题目并开始练习'}).click();
 await expect(page.locator('.question-card')).toHaveCount(2);await page.locator('.question-card').first().getByRole('button',{name:'检查 / 编辑'}).click();await expect(page.getByAltText('原始题目截图')).toBeVisible();
 await page.getByRole('checkbox',{name:'已对照原题，确认文字、公式和题号'}).check();await page.getByRole('button',{name:'保存题目',exact:true}).click();await expect(page.locator('.modal-backdrop')).toHaveCount(0);
 await page.locator('.question-card').first().getByRole('button',{name:'开始练习'}).click();await expect(page.getByAltText('题目原始截图 1')).toBeVisible();await page.getByLabel('解题笔记',{exact:true}).fill('已确认原始截图，开始分部积分。');await expect(page.locator('.save-status')).toContainText('已保存');
});

test('stale local draft cannot overwrite a newer database note on reopen',async({page,request})=>{
 const q=await request.post('/api/questions',{data:{text:'缓存冲突验收题目。',number:'CACHE-'+Date.now(),confirmed:true}});const {id}=await q.json();
 await request.put('/api/questions/'+id+'/attempt',{data:{notes:'数据库中的最新笔记',expected_updated_at:null}});
 await page.goto('/');await page.evaluate(({id})=>{const tab=sessionStorage.getItem('mathmaster-tab-id');localStorage.setItem('mathmaster-unsaved-'+id+'-'+tab,JSON.stringify({baseVersion:null,attempt:{answer:'旧答案',notes:'尚未同步的旧笔记',draft:'[]',status:'作答中',wrong:false}}));},{id});
 await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.locator('.question-card').filter({hasText:'缓存冲突验收题目'}).getByRole('button',{name:/开始练习|继续作答/}).click();
 await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('数据库中的最新笔记');await expect(page.getByRole('button',{name:'下载未同步草稿'})).toBeVisible();
 await page.waitForTimeout(1000);expect((await (await request.get('/api/questions/'+id)).json()).attempt.notes).toBe('数据库中的最新笔记');
 await page.getByRole('button',{name:'将旧草稿加载到编辑器'}).click();await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('尚未同步的旧笔记');await expect(page.locator('.save-status')).toContainText('已保存');
});
