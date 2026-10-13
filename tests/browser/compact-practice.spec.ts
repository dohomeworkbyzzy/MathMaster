import {test,expect} from '@playwright/test';

test('small practice windows prioritize the question and paper and preserve notes and ink',async({page,request})=>{
 const number='COMPACT-'+Date.now();
 const {id}=await (await request.post('/api/questions',{data:{number,text:Array.from({length:24},(_,i)=>`条件 ${i+1}：求积分并写出计算过程。`).join('\n'),confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 await page.getByLabel('解题笔记',{exact:true}).fill('缩小前的笔记');await page.getByLabel('我的答案').fill('原答案');
 const paper=page.getByLabel('电子草稿画布');await page.locator('.sketch-paper').scrollIntoViewIfNeeded();const box=(await page.locator('.sketch-paper').boundingBox())!;
 await page.mouse.move(box.x+20,box.y+30);await page.mouse.down();await page.mouse.move(box.x+70,box.y+60,{steps:5});await page.mouse.up();
 await expect.poll(async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length).toBe(1);
 for(const viewport of [{width:640,height:520},{width:480,height:420},{width:1000,height:640}]){
  await page.setViewportSize(viewport);
  await expect(page.getByRole('button',{name:'展开计算器',exact:true})).toBeVisible();
  await expect(page.getByLabel('解题笔记',{exact:true})).toBeHidden();
  await expect.poll(async()=>{const q=(await page.getByRole('region',{name:'题目区'}).boundingBox())!,p=(await paper.boundingBox())!;return q.width>viewport.width*.9&&p.width>viewport.width*.9&&p.y<viewport.height-90;}).toBeTruthy();
  const visible=await page.locator('.sketch-paper').boundingBox();
  expect(visible!.height).toBeGreaterThan(90);expect(visible!.y+visible!.height).toBeLessThanOrEqual(viewport.height+1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy();
  if(viewport.width===640)await page.screenshot({path:'docs/screenshots/compact-practice.png'});
 }
 const question=page.getByRole('region',{name:'题目区'});
 expect(await question.evaluate(el=>el.scrollHeight>el.clientHeight)).toBeTruthy();
 await question.evaluate(el=>el.scrollTop=el.scrollHeight);
 expect(await question.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
 await page.getByRole('button',{name:'笔记与答案',exact:true}).click();
 await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('缩小前的笔记');
 await expect(page.getByLabel('我的答案')).toHaveValue('原答案');
 await page.getByLabel('解题笔记',{exact:true}).fill('小窗更新的笔记');
 await page.getByRole('button',{name:'收起笔记',exact:true}).click();
 await page.getByRole('button',{name:'展开计算器',exact:true}).click();await expect(page.getByRole('button',{name:'收起计算器',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'收起计算器',exact:true}).click();
 await page.setViewportSize({width:1440,height:1000});
 await expect(page.getByLabel('解题笔记',{exact:true})).toHaveValue('小窗更新的笔记');
 await expect.poll(async()=>{const q=await (await request.get('/api/questions/'+id)).json();return [q.attempt?.notes,q.attempt?.answer,JSON.parse(q.attempt?.draft||'[]').length];}).toEqual(['小窗更新的笔记','原答案',1]);
});

test('paper, preview and saved ink follow the OS scheme and selected skin',async({page,request})=>{
 await page.emulateMedia({colorScheme:'dark'});
 await page.addInitScript(()=>{class Stream {onmessage:((event:{data:string})=>void)|null=null;onerror=null;constructor(){(window as any).__pad=this;}close(){}}(window as any).EventSource=Stream;});
 await page.route('**/api/touchpad/start',route=>route.fulfill({json:{token:'theme-native-test-session-token',devices:[{x_range:[0,1000],y_range:[0,600],aspect_ratio:1.65}]}}));
 await page.route('**/api/touchpad/stop',route=>route.fulfill({json:{stopped:true}}));
 const number='THEME-'+Date.now();await request.post('/api/questions',{data:{number,text:'主题书写验收',confirmed:true}});
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 const paper=page.getByLabel('电子草稿画布');
 await expect.poll(()=>paper.evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(36, 38, 40)');
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toBeVisible();
 await paper.evaluate(el=>{const r=el.getBoundingClientRect();(window as any).__pad.onmessage({data:JSON.stringify({type:'mouse',screen_x:screenX+r.left+r.width*.4,screen_y:screenY+outerHeight-innerHeight+r.top+70})});});
 const preview=page.getByLabel('放大笔迹');await expect(preview).toBeVisible();
 expect(await preview.evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(36, 38, 40)');
 await page.evaluate(()=>{for(const event of [{type:'contact',down:true,id:1,x:.2,y:.3},{type:'contact',down:true,id:1,x:.6,y:.5},{type:'contact',down:false}])(window as any).__pad.onmessage({data:JSON.stringify(event)});});
 expect(await preview.locator('path:not(.touchpad-center)').evaluate(el=>getComputedStyle(el).stroke)).toBe('rgb(229, 231, 233)');
 await page.keyboard.press('Escape');
 await page.emulateMedia({colorScheme:'light'});
 await expect.poll(()=>paper.evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(255, 255, 255)');
 await expect.poll(()=>paper.evaluate(el=>(el as HTMLCanvasElement).getContext('2d')!.strokeStyle)).toBe('#333333');
 await page.getByRole('button',{name:'切换皮肤',exact:true}).click();await page.getByRole('button',{name:'VS Code',exact:true}).click();
 await expect.poll(()=>paper.evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(30, 30, 30)');
 await expect.poll(()=>paper.evaluate(el=>(el as HTMLCanvasElement).getContext('2d')!.strokeStyle)).toBe('#d4d4d4');
});
