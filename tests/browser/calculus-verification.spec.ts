import {test,expect} from '@playwright/test';

for(const mobile of [false,true])test(`derivative checks show submitted formula and verdict on ${mobile?'phone':'desktop'}`,async({page,request})=>{
 const tag='偏导核验-'+Date.now();
 const q=await(await request.post('/api/questions',{data:{number:'1',subject:'数学二',text:tag+' 求偏导',confirmed:true}})).json();
 const session=await(await request.post('/api/questions/'+q.id+'/ai')).json();
 const results=[{verdict:'not_equal',operation:'check_derivative',result_latex:'2x',proposed_latex:'x',counterexample:{functions:{'f(t)':'t**2'},values:{x:'1'},left:'2',right:'1'},warnings:['仅核验公共定义域。']},{verdict:'undetermined',result_latex:'f(x)'},{verdict:'symbolically_equal_on_common_domain',result_latex:'2x'}];
 session.state.cards=results.map((result,i)=>({number:i+1,tool:'math.check_derivative',label:'偏导核验 '+(i+1),valid:true,input:{},result}));
 await page.route('**/api/questions/'+q.id+'/ai',r=>r.fulfill({json:session}));
 await page.route('**/api/ai/provider',r=>r.fulfill({json:{configured:true,model_id:'fixture'}}));
 if(mobile){
  await page.setViewportSize({width:390,height:844});await page.goto('/mobile');
  await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:/开始练习/}).filter({hasText:tag}).click();
  await page.getByRole('button',{name:'AI 解题 / 推荐',exact:true}).click();
 }else{
  await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);
  await page.getByRole('button',{name:'开始练习',exact:true}).click();await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 }
 await expect(page.getByText('核验不通过',{exact:true})).toBeVisible();
 await expect(page.getByText('暂时无法确认',{exact:true})).toBeVisible();
 await expect(page.getByText('核验通过',{exact:true})).toBeVisible();
 await expect(page.getByText('你提交的式子：',{exact:true})).toBeVisible();
 await expect(page.locator('.ai-verification').filter({hasText:'核验不通过'})).toContainText('参考值为 2，提交值为 1');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
