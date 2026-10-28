import {test,expect} from '@playwright/test';

test.use({viewport:{width:390,height:844},userAgent:'Mozilla/5.0 MathMasterMobile/0.1.1'});

test('mobile settings owns server management and changing users saves work under the original identity',async({page,request})=>{
 const tag='手机用户-'+Date.now();
 const q=await(await request.post('/api/questions',{data:{number:'1',subject:'数学二',text:tag+' 共用题库',confirmed:true}})).json();
 await page.goto('/mobile');
 await expect(page.getByRole('button',{name:'选择用户，当前 zzy'})).toBeVisible();
 await expect(page.locator('.m-header')).not.toContainText('http');
 await expect(page.getByRole('link',{name:'管理服务器地址'})).toHaveCount(0);
 await page.getByLabel('搜索题库').fill(tag);await page.locator('.m-question-card').filter({hasText:tag}).click();
 await page.getByLabel('做题笔记',{exact:true}).fill('zzy 的手机笔记，切换前未上传');
 await page.getByRole('button',{name:'选择用户，当前 zzy'}).click();await page.getByLabel('新用户名').fill('手机访客');await page.getByRole('button',{name:'注册并进入'}).click();
 await expect(page.getByRole('button',{name:'选择用户，当前 手机访客'})).toBeVisible();
 expect((await(await request.get('/api/questions/'+q.id,{headers:{'X-MathMaster-User':'zzy'}})).json()).attempt.notes).toBe('zzy 的手机笔记，切换前未上传');
 await page.getByLabel('搜索题库').fill(tag);await page.locator('.m-question-card').filter({hasText:tag}).click();await expect(page.getByLabel('做题笔记',{exact:true})).toHaveValue('');
 await page.getByLabel('做题笔记',{exact:true}).fill('访客独立笔记');
 await page.getByRole('button',{name:'选择用户，当前 手机访客'}).click();await page.getByRole('button',{name:'选择 zzy',exact:true}).click();
 await expect(page.getByRole('button',{name:'选择用户，当前 zzy'})).toBeVisible();
 await page.getByLabel('搜索题库').fill(tag);await page.locator('.m-question-card').filter({hasText:tag}).click();await expect(page.getByLabel('做题笔记',{exact:true})).toHaveValue('zzy 的手机笔记，切换前未上传');
 await page.getByRole('navigation',{name:'手机导航'}).getByRole('button',{name:'设置',exact:true}).click();
 await expect(page.getByRole('link',{name:'管理服务器地址'})).toHaveAttribute('href','mathmaster://settings/servers');
 await expect(page.locator('.m-header')).not.toContainText('http');
 await expect(page.getByText('当前连接：',{exact:false})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'artifacts/mobile-settings-0.1.1.png',fullPage:true});
});
