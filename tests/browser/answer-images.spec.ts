import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

function photo(){return execFileSync('/home/zzy18/.local/share/math-408-agent/venv/bin/python',['-c',"import io,sys;from PIL import Image;f=io.BytesIO();Image.new('RGB',(400,300),'white').save(f,'PNG');sys.stdout.buffer.write(f.getvalue())"]);}
async function practice(page:any,tag:string){await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();await page.getByLabel('搜索题库').fill(tag);await page.getByRole('button',{name:'开始练习',exact:true}).click();}

test('AI choices persist as the current answer and can be sent to the tutor without marking first',async({page,request})=>{
 const tag='AI选项-'+Date.now();const q=await (await request.post('/api/questions',{data:{number:'1',text:tag+' · 选择题 · 2分\n(A) $x$\n(B) $2x$\n(C) $3x$\n(D) $4x$',subject:'数学二',reference_answer:'B',confirmed:true}})).json();
 await page.route('**/api/ai/provider',route=>route.fulfill({json:{configured:true,model_id:'deepseek-flash',base_url:'https://api.deepseek.com'}}));
 let session:any;page.on('response',async r=>{if(r.url().endsWith('/api/questions/'+q.id+'/ai')&&r.ok())session=await r.json();});
 await page.route('**/api/ai/sessions/*/turns',async route=>{expect(route.request().postDataJSON().text).toContain('我选择 B');await route.fulfill({status:202,json:{...session,busy:false,version:1,turns:[{id:'choice-turn',user_text:route.request().postDataJSON().text,message:'你选择 B，先说说为什么。',status:'complete',error:''}]}});});
 await practice(page,tag);await page.getByRole('button',{name:'AI 解题',exact:true}).click();const ai=page.getByRole('region',{name:'AI 解题'});
 await ai.getByRole('radio',{name:'B',exact:true}).check();await expect.poll(async()=>(await (await request.get('/api/questions/'+q.id)).json()).attempt?.answer).toBe('B');
 await page.getByRole('button',{name:'按此答案继续分析',exact:true}).click();await expect(ai).toContainText('先说说为什么');
 await page.getByRole('button',{name:'提交答案 / 图片批改',exact:true}).click();await expect(page.getByRole('dialog').getByRole('radio',{name:'B',exact:true})).toBeChecked();
 await expect(page.getByRole('dialog').locator('.answer-choices')).toContainText('2x');
});

test('fill and subjective answer photos persist, record history and explicit scoring points are editable',async({page,request})=>{
 const tag='图片作答-'+Date.now();const q=await (await request.post('/api/questions',{data:{number:'1',text:tag+' · 解答题 · 6分\n求 x^2 的导数并写出求导规则。',subject:'数学二',reference_answer:'2x',confirmed:true}})).json();
 await practice(page,tag);await page.getByRole('button',{name:'答案与批改',exact:true}).click();const dialog=page.getByRole('dialog');
 await dialog.getByLabel('上传作答图片',{exact:true}).setInputFiles({name:'answer.png',mimeType:'image/png',buffer:photo()});await expect(dialog.locator('.answer-photo-list img')).toHaveCount(1);
 await dialog.getByRole('button',{name:'保存答案记录',exact:true}).click();await expect(dialog).toContainText('本题答案记录（1）');
 await page.getByRole('button',{name:'关闭答案批改',exact:true}).click();await page.getByRole('button',{name:'答案与批改',exact:true}).click();await expect(dialog.locator('.answer-photos img')).toHaveCount(1);
 await dialog.locator('.grading-rules summary').click();await page.getByRole('button',{name:'编辑评分要求',exact:true}).click();
 await page.getByLabel('评分说明与要求').fill('按实际写出的求导规则与结论分别给分');await page.getByRole('button',{name:'添加评分点',exact:true}).click();await page.getByLabel('评分点 1',{exact:true}).fill('写出幂函数求导规则');await page.getByLabel('评分点分值 1',{exact:true}).fill('2');
 await page.getByRole('button',{name:'添加评分点',exact:true}).click();await page.getByLabel('评分点 2',{exact:true}).fill('写出正确结论 2x');await page.getByText('已核对这些评分条件和分值，按此自动评分',{exact:true}).click();
 await page.getByRole('button',{name:'保存评分要求',exact:true}).click();await expect(dialog.locator('.grading-rules summary')).toContainText('已核对');
 const record=await (await request.get('/api/grading/questions/'+q.id)).json();expect(record.spec.scoring_rules.criteria.map((c:any)=>c.max_points)).toEqual([2,4]);expect(record.history[0].images).toHaveLength(1);
 await dialog.getByRole('button',{name:'移除第 1 张',exact:true}).click();await expect(dialog.locator('.answer-photos img')).toHaveCount(0);expect((await (await request.get('/api/grading/questions/'+q.id)).json()).history[0].images).toHaveLength(1);
 await page.setViewportSize({width:800,height:600});await expect(dialog.getByLabel('上传作答图片',{exact:true})).toBeVisible();
});

test('whole paper photo answer autosaves and resumes without losing its attachment',async({page,request})=>{
 const doc=execFileSync('/home/zzy18/.local/share/math-408-agent/venv/bin/python',['-c',"import io,sys;from docx import Document;d=Document();d.add_paragraph('1. 填空题 · 5分 求 x^2 的导数。');f=io.BytesIO();d.save(f);sys.stdout.buffer.write(f.getvalue())"]);
 const imported=await (await request.post('/api/papers/import',{multipart:{file:{name:'图片整卷.docx',mimeType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',buffer:doc},subject:'数学二'}})).json();
 await page.goto('/');await page.getByRole('button',{name:'整卷批改',exact:true}).click();await page.getByLabel('整卷试卷').selectOption(imported.id);await page.getByRole('button',{name:'新建整卷作答',exact:true}).click();
 await page.getByLabel('上传作答图片',{exact:true}).setInputFiles({name:'filled.png',mimeType:'image/png',buffer:photo()});await expect(page.locator('.answer-photo-list img')).toHaveCount(1);await expect(page.locator('.exam-toolbar').first()).toContainText('已答 1 / 1');
 await page.getByRole('button',{name:'返回试卷列表',exact:true}).click();await page.getByRole('button',{name:/打开记录/}).first().click();await expect(page.locator('.answer-photo-list img')).toHaveCount(1);
 const runs=await (await request.get('/api/grading/papers/'+imported.id+'/runs')).json();const resumed=await (await request.get('/api/grading/runs/'+runs[0].id)).json();expect(Object.values(resumed.answers).some((a:any)=>a.images?.length===1)).toBeTruthy();
 const qid=resumed.questions[0].id;expect((await request.put('/api/grading/questions/'+qid+'/rules',{data:{instructions:'按正确结果判分',source:'测试评分要求',verified:true,criteria:[{id:'result',description:'正确写出 2x',max_points:5}]}})).ok()).toBeTruthy();
 await page.getByRole('button',{name:'返回试卷列表',exact:true}).click();await page.getByRole('button',{name:/打开记录/}).first().click();await page.getByRole('button',{name:'复制作答并更新评分要求',exact:true}).click();
 await expect(page.getByRole('button',{name:'复制作答并更新评分要求',exact:true})).toBeHidden();await expect(page.locator('.answer-photo-list img')).toHaveCount(1);
 const updated=await (await request.get('/api/grading/papers/'+imported.id+'/runs')).json();expect(updated).toHaveLength(2);const old=await (await request.get('/api/grading/runs/'+runs[0].id)).json();expect(old.answers).toEqual(resumed.answers);expect(old.questions[0].spec.scoring_rules).toBeUndefined();
});
