import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

test('question OCR comes from durable knowledge and clearing response cache retains it',async({page,request})=>{
 const tag='预解析OCR-'+Date.now();const q=await (await request.post('/api/questions',{data:{number:tag,text:'填空题 · 5分\n请阅读下方原始题图，公式以图片为准。',subject:'数学二',reference_answer:'1',confirmed:false}})).json();
 const seed=`import os,sys\nos.environ['MATHMASTER_DATA']=sys.argv[1]\nfrom backend import db\nfrom backend.ai import knowledge as k\nfrom PIL import Image\nImage.new('RGB',(600,400),'white').save(db.DATA/'uploads/kb.png')\nwith db.connection() as c:\n c.execute('UPDATE questions SET images=? WHERE id=?',('["kb.png"]',sys.argv[2]));q=k.bank_question(c,sys.argv[2])\np={'question_id':q['id'],'question_text':'求 $\\\\sin(x)/x$ 在 $x\\\\to0$ 的极限','uncertain':False,'has_diagram':False,'topic':'基本极限','problem':{'kind':'limit','expression':'sin(x)/x'},'methods':[{'name':'泰勒展开','first_question':'保留几阶？'}],'private_solution':'PRIVATE_REFERENCE_1','rubric':'过程分','solution_basis':'reference'}\nk.put(q,p,'测试参考资料')`;
 execFileSync('/home/zzy18/.local/share/math-408-agent/venv/bin/python',['-c',seed,resolve('.test-data/ai-browser'),q.id],{cwd:resolve('.')});
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,base_url:'https://api.deepseek.com',model_id:'deepseek-flash'}}));
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();await page.getByRole('button',{name:'AI 解题',exact:true}).click();
 await expect(page.getByLabel('AI 识别题干')).toHaveValue(/sin/);await expect(page.locator('.ai-ocr')).not.toContainText('PRIVATE_REFERENCE');
 await page.getByRole('button',{name:'本地缓存',exact:true}).click();await expect(page.locator('.ai-knowledge-info')).toContainText('试卷预解析库');
 const before=await (await request.get('/api/ai/knowledge')).json();expect(before.metrics.ocr_hits).toBeGreaterThan(0);
 await page.getByRole('button',{name:'清空缓存',exact:true}).click();await expect.poll(async()=>(await (await request.get('/api/ai/knowledge')).json()).stored_questions).toBe(before.stored_questions);
 expect((await (await request.get('/api/ai/cache')).json()).categories.find((c:any)=>c.namespace==='ocr')?.remote_calls||0).toBe(0);
 await page.getByRole('button',{name:'确认并保存到题库'}).click();await expect(page.getByLabel('AI 识别题干')).toBeHidden();
 const bank=await (await request.get('/api/grading/questions/'+q.id)).json();expect(bank.spec.max_points).toBe(5);
});
