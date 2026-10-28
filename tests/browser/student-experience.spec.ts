import {test,expect} from '@playwright/test';

test('student finds a question, answers it, and returns to the mistake list',async({page,request})=>{
 const tag='STUDENT-'+Date.now();
 const q=await (await request.post('/api/questions',{data:{number:tag,subject:'408',text:'选择题 · 2分\n操作系统负责管理什么？\nA. 软件 B. 硬件 C. 计算机资源 D. 应用程序',reference_answer:'C',confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill('找不到的题目-'+tag);
 await expect(page.getByRole('heading',{name:'没有找到符合条件的题目'})).toBeVisible();
 await page.getByRole('button',{name:'清除筛选'}).click();await expect(page.getByLabel('搜索题库')).toHaveValue('');
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();
 const answer=page.getByRole('radiogroup',{name:'我的答案'});
 await expect(answer).toContainText('计算机资源');
 await expect(answer.locator('label').first()).toHaveText(/A\s*软件\s*$/);
 const positions=await page.evaluate(()=>{const a=document.querySelector('.question-answer')!.getBoundingClientRect();const n=document.querySelector('.notes-editor')!.getBoundingClientRect();return {answer:a.top,note:n.top};});
 expect(positions.answer).toBeLessThan(positions.note);
 await answer.getByRole('radio',{name:'C',exact:true}).check();await page.getByRole('button',{name:'加入错题本'}).click();
 await page.getByRole('button',{name:'完成本题'}).click();await expect.poll(async()=>(await (await request.get('/api/questions/'+q.id)).json()).attempt?.answer).toBe('C');
 await page.getByRole('button',{name:'错题本',exact:true}).click();
 await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 await expect(page.getByRole('radiogroup',{name:'我的答案'}).getByRole('radio',{name:'C',exact:true})).toBeChecked();
 await page.getByRole('button',{name:'返回错题本'}).click();await expect(page.getByRole('heading',{name:'错题本',exact:true})).toBeVisible();
 await page.setViewportSize({width:620,height:600});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy();
 await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();await page.getByRole('button',{name:'笔记与答案'}).click();
 await expect(page.getByRole('radiogroup',{name:'我的答案'}).getByRole('radio',{name:'C',exact:true})).toBeChecked();
 await page.getByRole('button',{name:'返回错题本'}).click();await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();await page.getByRole('button',{name:'打开错题本'}).click();
 await expect(page.getByRole('heading',{name:'错题本',exact:true})).toBeVisible();
});

test('switching to mistake review never exposes the previous library results while loading',async({page,request})=>{
 const tag='SLOW-LIST-'+Date.now();
 await request.post('/api/questions',{data:{number:tag,subject:'408',text:'不属于错题的普通题目',confirmed:true}});
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);
 await expect(page.locator('.question-card')).toHaveCount(1);
 await page.route('**/api/questions?*',async route=>{if(route.request().url().includes('wrong=true'))await new Promise(resolve=>setTimeout(resolve,700));await route.continue();});
 await page.getByRole('button',{name:'错题本',exact:true}).click();
 await expect(page.locator('.question-card')).toHaveCount(0);await expect(page.getByText('读取本地题库…')).toBeVisible();
 await expect(page.getByRole('heading',{name:'没有找到符合条件的题目'})).toBeVisible();
});
