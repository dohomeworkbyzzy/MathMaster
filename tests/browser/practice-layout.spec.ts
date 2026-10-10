import {test,expect} from '@playwright/test';

test('question and draft share vertical space; auto, drag and sidebar controls work',async({page,request})=>{
 const prefix='上下布局-'+Date.now();
 for(const [number,text] of [['短题',`${prefix}短题：计算 $\\int x e^x dx$。`],['长题',`${prefix}长题\n`+Array.from({length:16},(_,i)=>`条件 ${i+1}：请根据给定函数计算，并写出完整过程。`).join('\n')]]){
  expect((await request.post('/api/questions',{data:{number,text,confirmed:true}})).ok()).toBeTruthy();
 }
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(prefix);await expect(page.locator('.question-card')).toHaveCount(2);
 await page.locator('.question-card').filter({hasText:'短题'}).getByRole('button',{name:'开始练习'}).click();
 const question=page.getByRole('region',{name:'题目区'}),draft=page.getByRole('region',{name:'草稿区'});
 const shortHeight=(await question.boundingBox())!.height;
 await page.getByRole('button',{name:'返回题库'}).click();
 await page.locator('.question-card').filter({hasText:'长题'}).getByRole('button',{name:'开始练习'}).click();
 await expect.poll(async()=>(await question.boundingBox())!.height).toBeGreaterThan(shortHeight+200);
 const beforeQuestion=(await question.boundingBox())!,beforeDraft=(await draft.boundingBox())!;
 expect(beforeDraft.y).toBeGreaterThan(beforeQuestion.y+beforeQuestion.height);
 expect(beforeDraft.height).toBeGreaterThanOrEqual(210);
 expect(await question.evaluate(el=>el.scrollHeight<=el.clientHeight+2)).toBeTruthy();
 const divider=page.getByRole('separator',{name:'调整题目与草稿高度'}),box=(await divider.boundingBox())!;
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2-130,{steps:8});await page.mouse.up();
 await expect(page.getByRole('button',{name:'自动调节：关'})).toBeVisible();
 await expect.poll(async()=>(await draft.boundingBox())!.height).toBeGreaterThan(beforeDraft.height+100);
 await page.getByRole('button',{name:'自动调节：关'}).click();
 await expect.poll(async()=>(await question.boundingBox())!.height).toBeGreaterThan(beforeQuestion.height-5);
 const width=(await question.boundingBox())!.width;
 await page.getByRole('button',{name:'收起侧栏'}).click();
 await page.getByRole('button',{name:'收起计算器'}).click();
 await expect.poll(async()=>(await question.boundingBox())!.width).toBeGreaterThan(width+300);
 await expect(page.getByRole('button',{name:'展开侧栏'})).toBeVisible();
 await expect(page.getByRole('button',{name:'展开计算器'})).toBeVisible();
 await expect(page.getByLabel('电子草稿画布')).toBeVisible();
 await page.getByRole('button',{name:'展开侧栏'}).click();await page.getByRole('button',{name:'展开计算器'}).click();
 await expect(page.getByRole('button',{name:'收起侧栏'})).toBeVisible();
 await page.setViewportSize({width:1100,height:800});
 await expect.poll(async()=>(await draft.boundingBox())!.height).toBeGreaterThanOrEqual(210);
 await expect.poll(async()=>page.getByLabel('电子草稿画布').evaluate(element=>{
  const canvas=element as HTMLCanvasElement,rect=canvas.getBoundingClientRect();
  return Math.abs(canvas.width/rect.width-canvas.height/rect.height);
 })).toBeLessThan(.01);
});
