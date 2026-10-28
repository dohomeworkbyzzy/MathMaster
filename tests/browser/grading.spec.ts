import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

test('single answer records survive closing and reopening; marks current answer',async({page,request})=>{
 const q=await (await request.post('/api/questions',{data:{number:'1',text:'选择题 · 2分\n以下答案选 A。',subject:'408',reference_answer:'A',confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill('以下答案选 A');
 await page.getByRole('button',{name:'开始练习'}).first().click();
 await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await page.getByRole('button',{name:'答案与批改',exact:true}).click();
 await page.getByRole('radio',{name:'A',exact:true}).check();await page.getByRole('button',{name:'保存答案记录'}).click();
 await expect(page.getByRole('dialog')).toContainText('本题答案记录（1）');
 await page.getByRole('button',{name:'核对当前题目'}).click();
 await expect(page.getByRole('dialog').locator('.grade-result')).toContainText('已评分 · 2 / 2 分');
 await page.getByRole('button',{name:'关闭答案批改'}).click();await page.getByRole('button',{name:'答案与批改',exact:true}).click();
 await expect(page.getByRole('radio',{name:'A',exact:true})).toBeChecked();await expect(page.getByRole('dialog')).toContainText('本题答案记录（2）');
 const saved=await (await request.get('/api/questions/'+q.id)).json();expect(saved.attempt.answer).toBe('A');
});

test('whole paper resumes autosaved answers, grades all questions, retains marks',async({page,request})=>{
 // Browser tests import a small real DOCX through the existing scanner endpoint.
 const buffer=execFileSync('/home/zzy18/.local/share/math-408-agent/venv/bin/python',['-c',`import sys,io
from docx import Document
d=Document();d.add_paragraph('1. 选择题 · 2分 以下答案选 A。');d.add_paragraph('2. 选择题 · 2分 以下答案选 B。');f=io.BytesIO();d.save(f);sys.stdout.buffer.write(f.getvalue())`]);
 const response=await request.post('/api/papers/import',{multipart:{file:{name:'整卷验收.docx',mimeType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',buffer},subject:'408'}});expect(response.ok()).toBeTruthy();const p=await response.json();
 const qs=await (await request.get('/api/questions?paper_id='+p.id)).json();expect(qs.length).toBe(2);
 for(const q of qs)await request.put('/api/questions/'+q.id,{data:{number:q.number,text:q.text,subject:'408',reference_answer:q.number==='1'?'A':'B',confirmed:true}});
 await page.goto('/');await page.getByRole('button',{name:'整卷批改',exact:true}).click();await page.getByLabel('整卷试卷').selectOption(p.id);await page.getByRole('button',{name:'新建整卷作答'}).click();
 await page.getByRole('radio',{name:'A',exact:true}).check();await page.getByRole('button',{name:'保存整卷',exact:true}).click();await expect(page.locator('.exam-toolbar').first()).toContainText('已保存');
 await page.getByRole('button',{name:'返回试卷列表'}).click();await page.getByRole('button',{name:/打开记录/}).first().click();await expect(page.getByRole('radio',{name:'A',exact:true})).toBeChecked();
 await page.getByRole('button',{name:'整套试卷批改'}).click();await expect(page.locator('.exam-score')).toContainText('总分：2 / 4');
 await page.getByRole('button',{name:'下一题',exact:true}).click();await expect(page.locator('.grade-result')).toContainText('未作答');await page.getByRole('radio',{name:'B',exact:true}).check();
 await expect(page.locator('.exam-score')).toContainText('作答已修改');await page.getByRole('button',{name:'整套试卷批改'}).click();await expect(page.locator('.exam-score')).toContainText('总分：4 / 4');
 await page.getByRole('button',{name:'返回试卷列表'}).click();await page.getByRole('button',{name:/打开记录/}).first().click();await expect(page.locator('.exam-score')).toContainText('总分：4 / 4');
});

test('completed AI answer and delegated steps auto-save while preserving existing notes',async({page,request})=>{
 const tag='自动记录AI-'+Date.now();const q=await (await request.post('/api/questions',{data:{number:tag,text:'求 x→0 时 sin(x)/x 的极限',subject:'数学二',reference_answer:'1',confirmed:true}})).json();
 let session:any;
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,base_url:'https://api.deepseek.com',model_id:'deepseek-flash'}}));
 page.on('response',async r=>{if(r.url().endsWith('/api/questions/'+q.id+'/ai')&&r.ok())session=await r.json();});
 await page.route('**/api/ai/sessions/*/turns',async route=>{
  expect(route.request().postDataJSON().text).toBe('所以我得到答案1');
  await route.fulfill({status:202,json:{...session,version:1,busy:false,turns:[{id:'final-answer',request_id:route.request().postDataJSON().request_id,user_text:'所以我得到答案1',message:'本次方法完成。',status:'complete',error:''}],state:{...session.state,final_answer:'1',final_answer_turn:'final-answer',answer_reasoning:'用户说明使用泰勒展开。\n计算步骤（系统代算）：$\\sin x=x+O(x^3)$',completed_methods:['泰勒展开'],next_question:''}}});
 });
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();
 await page.getByLabel('解题笔记',{exact:true}).fill('原来的笔记');await page.getByRole('button',{name:'AI 解题',exact:true}).click();await expect.poll(()=>session?.id).toBeTruthy();
 await page.getByLabel('描述解题思路').fill('所以我得到答案1');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect.poll(async()=>(await (await request.get('/api/questions/'+q.id)).json()).attempt?.answer).toBe('1');
 const stored=await (await request.get('/api/questions/'+q.id)).json();expect(stored.attempt.notes).toContain('原来的笔记');expect(stored.attempt.notes).toContain('系统代算');
 await page.getByRole('button',{name:'答案与批改',exact:true}).click();await expect(page.getByRole('dialog').getByLabel('记录的答案')).toHaveValue('1');
});
