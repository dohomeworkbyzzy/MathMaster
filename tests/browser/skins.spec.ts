import {test,expect} from '@playwright/test';

async function choose(page:import('@playwright/test').Page,name:string){
 await page.getByRole('button',{name:'切换皮肤',exact:true}).click();
 await page.getByRole('button',{name,exact:true}).click();
}

test('skins preserve live notes, answers and ink; cover restores the same workspace',async({page,request})=>{
 const number='SKIN-'+Date.now();
 const {id}=await (await request.post('/api/questions',{data:{number,text:'计算 $\\int x e^x dx$。',confirmed:true}})).json();
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 await page.getByLabel('解题笔记',{exact:true}).fill('切换前的笔记');await page.getByLabel('我的答案').fill('保留答案');
 const box=(await page.getByLabel('电子草稿画布').boundingBox())!;
 await page.mouse.move(box.x+20,box.y+30);await page.mouse.down();await page.mouse.move(box.x+90,box.y+50,{steps:5});await page.mouse.up();
 for(const [name,id] of [['VS Code','code'],['Word 文档','word'],['Excel 表格','sheet']]){
  await choose(page,name);await expect(page.locator('.app')).toHaveClass(new RegExp('skin-'+id));
  await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('切换前的笔记');
  await expect(page.getByLabel('我的答案')).toHaveValue('保留答案');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy();
  await page.screenshot({path:'docs/screenshots/skin-'+id+'.png'});
 }
 await page.getByLabel('解题笔记',{exact:true}).fill('F8 前尚在编辑的笔记');
 await page.keyboard.press('F8');await expect(page.getByRole('dialog',{name:'工作报告',exact:true})).toBeVisible();
 await expect(page).toHaveTitle('项目进度周报.docx - Word');
 await expect(page.locator('.app')).toHaveAttribute('inert','');
 await page.screenshot({path:'docs/screenshots/skin-cover.png'});
 await page.keyboard.press('F8');await expect(page.getByRole('dialog',{name:'工作报告',exact:true})).toHaveCount(0);
 await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('F8 前尚在编辑的笔记');
 await expect.poll(async()=>{const q=await (await request.get('/api/questions/'+id)).json();return [q.attempt?.notes,q.attempt?.answer,JSON.parse(q.attempt?.draft||'[]').length];}).toEqual(['F8 前尚在编辑的笔记','保留答案',1]);
 await page.getByRole('button',{name:'返回题库'}).click();await page.reload();
 await expect(page.locator('.app')).toHaveClass(/skin-sheet/);await expect(page).toHaveTitle('数据分析工作簿.xlsx - Excel');
 await choose(page,'原版');await expect(page.getByRole('heading',{name:'数学计算工作台'})).toBeVisible();
 expect(errors).toEqual([]);
});

test('skin menu, cover and calculator work at compact window sizes',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('mathmaster-skin','invalid-skin'));
 await page.goto('/');await expect(page.locator('.app')).toHaveClass(/skin-original/);
 // Text inputs and results must survive a cover even when the calculator is fullscreen.
 await page.getByRole('button',{name:'文本表达式',exact:true}).click();await page.getByLabel('文本表达式',{exact:true}).fill('x^2');
 await page.getByRole('button',{name:'全屏',exact:true}).click();await page.keyboard.press('F8');
 await page.getByRole('button',{name:'返回工作区 F8',exact:true}).click();
 await expect(page.getByLabel('文本表达式',{exact:true})).toHaveValue('x^2');
 await page.getByRole('button',{name:'退出全屏',exact:true}).click();
 await page.setViewportSize({width:620,height:470});
 for(const name of ['VS Code','Word 文档','Excel 表格','原版']){
  await choose(page,name);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy();
  await expect(page.getByRole('button',{name:'切换皮肤',exact:true})).toBeVisible();
  await page.keyboard.press('F8');await expect(page.getByRole('dialog',{name:'工作报告',exact:true})).toBeVisible();
  await page.keyboard.press('F8');
 }
 await choose(page,'VS Code');await page.getByRole('button',{name:'开始计算',exact:true}).click();await expect(page.locator('.verified-badge')).toHaveText('验证通过',{timeout:20000});
 await expect(page.locator('.answer-box')).toContainText('3');
});

test('cover commits native ink and cancels a pending touchpad start',async({page,request})=>{
 const number='COVER-INK-'+Date.now();
 const {id}=await (await request.post('/api/questions',{data:{number,text:'触控板切换验收',confirmed:true}})).json();
 await page.addInitScript(()=>{
  class Stream {onmessage:((event:{data:string})=>void)|null=null;onerror=null;constructor(){(window as any).__pad=this;}close(){}}
  (window as any).EventSource=Stream;
 });
 const session={token:'skin-test-session-owner-token',devices:[{x_range:[0,1000],y_range:[0,600],aspect_ratio:1.65}]};
 await page.route('**/api/touchpad/start',route=>route.fulfill({json:session}));
 let stops=0;await page.route('**/api/touchpad/stop',route=>{stops++;return route.fulfill({json:{stopped:true}});});
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(number);
 await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toBeVisible();
 await page.getByLabel('电子草稿画布').evaluate(el=>{const box=el.getBoundingClientRect();(window as any).__pad.onmessage({data:JSON.stringify({type:'mouse',screen_x:window.screenX+box.left+box.width*.3,screen_y:window.screenY+window.outerHeight-window.innerHeight+box.top+30})});});
 await page.evaluate(()=>{for(const event of [{type:'contact',down:true,id:1,x:.1,y:.2},{type:'contact',down:true,id:1,x:.3,y:.4}])(window as any).__pad.onmessage({data:JSON.stringify(event)});});
 await page.keyboard.press('F8');await expect(page.getByRole('dialog',{name:'工作报告',exact:true})).toBeVisible();
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toHaveCount(0);
 await page.keyboard.press('F8');await expect(page.getByRole('button',{name:'触控板书写',exact:true})).toHaveAttribute('aria-pressed','false');
 await expect.poll(async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length).toBe(1);
 await expect.poll(()=>stops).toBe(1);
 let pending:import('@playwright/test').Route|undefined;
 await page.route('**/api/touchpad/start',route=>{pending=route;});
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();await expect.poll(()=>Boolean(pending)).toBe(true);
 await page.keyboard.press('F8');await expect(page.getByRole('dialog',{name:'工作报告',exact:true})).toBeVisible();await page.keyboard.press('F8');
 await pending!.fulfill({json:session});await expect.poll(()=>stops).toBe(2);
 await expect(page.getByRole('button',{name:'触控板书写',exact:true})).toHaveAttribute('aria-pressed','false');
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toHaveCount(0);
});
