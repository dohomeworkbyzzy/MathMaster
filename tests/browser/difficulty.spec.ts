import {test,expect} from '@playwright/test';

test('difficulty is visible and personally editable; recommendation previews its level before opening',async({page,request})=>{
 const tag='DIFFICULTY-'+Date.now();
 const source=await (await request.post('/api/questions',{data:{number:tag,text:'判断泰勒展开的适用条件',subject:'数学二',confirmed:true}})).json();
 const next=await (await request.post('/api/questions',{data:{number:tag+'-challenge',text:'分析主导项抵消后的阶数',subject:'数学二',confirmed:true}})).json();
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,model_id:'fixture'}}));
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.locator('.question-card').filter({hasText:tag}).filter({hasNotText:tag+'-challenge'}).getByRole('button',{name:'开始练习'}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 const panel=page.locator('.difficulty-panel');
 await expect(panel).toContainText('难度待确认');
 await page.getByLabel('个人校正题目难度').selectOption('3');
 await expect(panel).toContainText('本题：标准');
 await expect(panel).toContainText('个人校正');
 expect((await (await request.get('/api/questions/'+source.id+'/difficulty')).json()).rating.level).toBe(3);
 await page.route('**/api/ai/sessions/*/recommend',async route=>{
  expect(route.request().postDataJSON()).toEqual({preference:'harder'});
  const rating=(await (await request.get('/api/questions/'+source.id+'/difficulty')).json()).rating;
  await route.fulfill({json:{question_id:next.id,number:next.number,reason:'本题：标准 → 下一题：进阶。按你的选择，挑战高一档。',current_difficulty:rating,difficulty:{...rating,level:4,label:'进阶'},target:{level:4,label:'进阶',goal_level:4,goal_label:'进阶',successes:0,failures:0,reason:'挑战高一档。'}}});
 });
 await page.getByRole('button',{name:'挑战一下',exact:true}).click();
 await page.getByRole('button',{name:'推荐下一题',exact:true}).click();
 await expect(panel.getByRole('status')).toContainText('标准 → 下一题：进阶');
 await page.screenshot({path:'test-results/difficulty-recommendation.png'});
 await expect(page.locator('.practice-title')).not.toContainText('-challenge');
 await panel.getByRole('button',{name:/开始推荐题/}).click();
 await expect(page.locator('.practice-title')).toContainText('-challenge');
 await expect(page.locator('.difficulty-result')).toHaveCount(0);
 await expect(page.getByLabel('电子草稿画布')).toBeVisible();
});

test('missing level keeps the current question and explains the gap',async({page,request})=>{
 const tag='DIFFICULTY-GAP-'+Date.now();
 const q=await (await request.post('/api/questions',{data:{number:tag,text:'同知识点难度缺口',confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习'}).click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect(page.getByLabel('个人校正题目难度')).toBeVisible();
 await page.getByLabel('个人校正题目难度').selectOption('4');
 await page.route('**/api/ai/sessions/*/recommend',async route=>{
  const value=await (await request.get('/api/questions/'+q.id+'/difficulty')).json();
  await route.fulfill({json:{question_id:null,gap:'no_matching_level',current_difficulty:value.rating,target:value.progress,reason:'当前相关候选中没有可用的“进阶”新题；未自动改推更简单或无关的题。'}});
 });
 await page.getByRole('button',{name:'推荐下一题',exact:true}).click();
 await expect(page.locator('.difficulty-result')).toContainText('没有可用');
 await expect(page.getByRole('button',{name:/开始推荐题/})).toHaveCount(0);
 await expect(page.locator('.practice-title')).toContainText(tag);
});
