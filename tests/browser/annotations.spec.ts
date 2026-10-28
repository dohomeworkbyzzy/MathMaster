import {test,expect,type Page,type APIRequestContext} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function prepare(request:APIRequestContext){
 const tag='标注试卷-'+Date.now();
 const response=await request.post('/api/papers/import',{multipart:{title:tag,subject:'数学二',file:{name:'exam.pdf',mimeType:'application/pdf',buffer:await readFile('tests/fixtures/exam.pdf')}}});
 expect(response.ok()).toBeTruthy();const paper=await response.json();
 const questions=await (await request.get('/api/questions?paper_id='+paper.id)).json();return {tag,questions};
}
async function open(page:Page,tag:string){
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);
 await page.locator('.question-card').first().getByRole('button',{name:/开始练习|继续作答/}).click();
 await expect(page.getByRole('button',{name:'标注题目',exact:true})).toBeEnabled();
}
async function draw(page:Page,y:number,whileDown?:()=>Promise<unknown>){
 const box=(await page.getByRole('img',{name:'题图标注层 1',exact:true}).boundingBox())!;
 await page.mouse.move(box.x+box.width*.2,box.y+box.height*y);await page.mouse.down();
 await page.mouse.move(box.x+box.width*.4,box.y+box.height*y,{steps:4});if(whileDown)await whileDown();
 await page.mouse.move(box.x+box.width*.65,box.y+box.height*y,{steps:4});await page.mouse.up();
}

test('image annotations save separately, follow resizing, undo erasing, and reopen across questions',async({page,request})=>{
 const {tag,questions:[q,next]}=await prepare(request);
 const original=await (await request.get('/api/files/'+q.images[0])).body();
 await open(page,tag);await page.getByLabel('解题笔记',{exact:true}).fill('草稿与标注独立');
 const canvas=(await page.getByLabel('电子草稿画布').boundingBox())!;
 await page.mouse.move(canvas.x+20,canvas.y+20);await page.mouse.down();await page.mouse.move(canvas.x+80,canvas.y+40,{steps:5});await page.mouse.up();
 await expect.poll(async()=>(await (await request.get('/api/questions/'+q.id)).json()).attempt?.notes).toBe('草稿与标注独立');
 const attempt=(await (await request.get('/api/questions/'+q.id)).json()).attempt;
 await page.getByRole('button',{name:'标注题目',exact:true}).click();await draw(page,.35);
 const overlay=page.getByRole('img',{name:'题图标注层 1',exact:true});await expect(overlay.locator('path')).toHaveCount(1);
 await page.getByRole('button',{name:'荧光笔',exact:true}).click();await draw(page,.7,()=>expect.poll(async()=>(await (await request.get('/api/questions/'+q.id+'/annotations')).json()).strokes.length).toBe(1));await expect(overlay.locator('path')).toHaveCount(2);
 await page.getByRole('button',{name:'撤销标注',exact:true}).click();await expect(overlay.locator('path')).toHaveCount(1);
 await page.getByRole('button',{name:'重做标注',exact:true}).click();await expect(overlay.locator('path')).toHaveCount(2);
 await page.getByRole('button',{name:'橡皮擦',exact:true}).click();
 const box=(await overlay.boundingBox())!;await page.mouse.click(box.x+box.width*.4,box.y+box.height*.35);
 await expect(overlay.locator('path')).toHaveCount(1);await page.getByRole('button',{name:'撤销标注',exact:true}).click();await expect(overlay.locator('path')).toHaveCount(2);
 await page.getByRole('button',{name:'清空标注',exact:true}).click();await expect(overlay.locator('path')).toHaveCount(0);
 await page.getByRole('button',{name:'撤销标注',exact:true}).click();await expect(overlay.locator('path')).toHaveCount(2);
 await page.getByRole('button',{name:'完成题目标注',exact:true}).click();
 const paths=await overlay.locator('path').evaluateAll(paths=>paths.map(p=>p.getAttribute('d')));
 await page.setViewportSize({width:1100,height:800});await page.getByRole('button',{name:'放大题图',exact:true}).click();
 const image=page.getByAltText('题目原始截图 1');const bounds=await image.boundingBox(),layer=await overlay.boundingBox();
 expect(layer!.x).toBeCloseTo(bounds!.x,0);expect(layer!.y).toBeCloseTo(bounds!.y,0);expect(layer!.width).toBeCloseTo(bounds!.width,0);expect(layer!.height).toBeCloseTo(bounds!.height,0);
 expect(await overlay.locator('path').evaluateAll(paths=>paths.map(p=>p.getAttribute('d')))).toEqual(paths);
 await page.getByRole('button',{name:'下一题',exact:true}).click();await expect(page.getByRole('img',{name:'题图标注层 1',exact:true}).locator('path')).toHaveCount(0);
 expect((await (await request.get('/api/questions/'+next.id+'/annotations')).json()).strokes).toEqual([]);
 const saved=await (await request.get('/api/questions/'+q.id+'/annotations')).json();expect(saved.strokes).toHaveLength(2);
 expect(saved.strokes[0].points[0].x).toBeCloseTo(.2,2);expect(saved.strokes[0].points.at(-1).x).toBeCloseTo(.65,2);expect(saved.strokes[1].points.at(-1).x).toBeCloseTo(.65,2);
 expect((await (await request.get('/api/questions/'+q.id)).json()).attempt).toEqual(attempt);
 expect(await (await request.get('/api/files/'+q.images[0])).body()).toEqual(original);
 await open(page,tag);await expect(page.getByRole('img',{name:'题图标注层 1',exact:true}).locator('path')).toHaveCount(2);
 await page.setViewportSize({width:1440,height:1000});await page.getByRole('button',{name:'切换皮肤',exact:true}).click();await page.getByRole('button',{name:'VS Code',exact:true}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect(page.getByRole('img',{name:'题图标注层 1',exact:true}).locator('path')).toHaveCount(2);
 await page.screenshot({path:'test-results/question-annotations.png'});
});

test('failed annotation saves recover after reload and are readable in a fresh browser context',async({page,request,browser})=>{
 const {tag,questions:[q]}=await prepare(request);await open(page,tag);
 await page.route('**/api/questions/'+q.id+'/annotations',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'测试保存暂时失败'}}):route.continue());
 await page.getByRole('button',{name:'标注题目',exact:true}).click();await draw(page,.4);
 await expect(page.locator('.annotation-error')).toContainText('测试保存暂时失败');
 await page.unroute('**/api/questions/'+q.id+'/annotations');await open(page,tag);
 await expect(page.getByRole('img',{name:'题图标注层 1',exact:true}).locator('path')).toHaveCount(1);
 await expect.poll(async()=>(await (await request.get('/api/questions/'+q.id+'/annotations')).json()).strokes.length).toBe(1);
 const context=await browser.newContext({baseURL:new URL(page.url()).origin});const fresh=await context.newPage();
 await open(fresh,tag);await expect(fresh.getByRole('img',{name:'题图标注层 1',exact:true}).locator('path')).toHaveCount(1);await context.close();
});
