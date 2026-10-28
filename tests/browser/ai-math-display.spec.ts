import {test,expect} from '@playwright/test';

const reply=String.raw`按 \(u_{xy}=\dfrac{\partial^2u}{\partial x\partial y}\) 核对，这条草稿不通过；这里的 \(u'\) 应理解为 \(\varphi'\)。正确结果是
\[
u_{xy}=\varphi'(x+y)-\varphi'(-x-y)+\varphi'(x-y)-\varphi'(-x+y).
\]
你草稿的第一、三、四项与它对应，主要错误在第二项：对 \(g(x+y)\) 求 \(y\) 导时，\(g'(x+y)=\varphi'(x+y)-\varphi'(-x-y)\)。

因此暂不继续计算其余二阶偏导。`;

for(const mobile of [false,true])test(`AI mathematical replies render and scroll within ${mobile?'phone':'desktop'}`,async({page,request})=>{
 const tag='公式显示-'+Date.now();
 const q=await(await request.post('/api/questions',{data:{number:'1',text:tag+' 核对混合偏导',subject:'数学二',confirmed:true}})).json();
 const session=await(await request.post('/api/questions/'+q.id+'/ai')).json();
 let message=reply;
 const view=()=>({...session,version:1,busy:false,turns:[{id:'display-test',user_text:'请核对我的混合偏导',message,status:'complete',error:''}]});
 await page.route('**/api/questions/'+q.id+'/ai',r=>r.fulfill({json:view()}));
 await page.route('**/api/ai/sessions/*',r=>r.fulfill({json:view()}));
 await page.route('**/api/ai/provider',r=>r.fulfill({json:{configured:true,model_id:'fixture'}}));
 if(mobile){
  await page.setViewportSize({width:390,height:844});await page.goto('/mobile');
  await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:/开始练习/}).filter({hasText:tag}).click();
  await page.getByRole('button',{name:'AI 解题 / 推荐',exact:true}).click();
 }else{
  await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
  await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();
  await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 }
 const response=page.locator(mobile?'.m-reply':'.ai-response');
 await expect(response.locator('.inline-formula')).toHaveCount(6);
 await expect(response.locator('.formula .katex-display')).toHaveCount(1);
 await expect(response.locator('.katex-error')).toHaveCount(0);
 await expect(response.locator('.rich-paragraph')).toHaveCount(3);
 const content=await response.innerText();
 expect(content).not.toContain('\\(');expect(content).not.toContain('\\[');expect(content).not.toContain('\\dfrac');
 const overflowing=await response.locator('.formula').evaluate(el=>el.scrollWidth>el.clientWidth);
 if(mobile)expect(overflowing).toBeTruthy();
 if(overflowing){
  await response.locator('.formula').evaluate(el=>{el.scrollLeft=10000;});
  expect(await response.locator('.formula').evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  await response.locator('.formula').evaluate(el=>{el.scrollLeft=0;});
 }
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await response.screenshot({path:`artifacts/ai-diagnostics/formula-${mobile?'phone':'desktop'}.png`});
 message=String.raw`保留原有行内写法 $x^2$ 和独立公式：
$$\frac{1}{2}$$

普通文字 <script>alert('unsafe')</script> 原样显示。
未闭合的 \(公式和 $5 保留原文。`;
 await expect(response.locator('.inline-formula')).toHaveCount(1,{timeout:10000});
 await expect(response.locator('.formula .katex-display')).toHaveCount(1);
 await expect(response.locator('script')).toHaveCount(0);
 await expect(response).toContainText("<script>alert('unsafe')</script>");
 await expect(response).toContainText(String.raw`未闭合的 \(公式和 $5 保留原文。`);
});
