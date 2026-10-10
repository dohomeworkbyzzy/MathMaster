import {test,expect} from '@playwright/test';

test('compact window action folds sidebar, restores, and small viewport remains usable',async({page})=>{
 const modes:string[]=[];
 await page.route('**/api/window',async route=>{
  const {mode}=route.request().postDataJSON();modes.push(mode);
  await route.fulfill({contentType:'application/json',body:JSON.stringify({mode})});
 });
 await page.goto('/');
 await page.getByRole('button',{name:'收缩窗口',exact:true}).click();
 await expect(page.getByRole('button',{name:'还原窗口',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'展开侧栏',exact:true})).toBeVisible();
 await page.setViewportSize({width:620,height:470});
 await expect(page.getByRole('button',{name:'还原窗口',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'最小化窗口',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2)).toBeTruthy();
 await page.getByRole('button',{name:'还原窗口',exact:true}).click();
 await expect(page.getByRole('button',{name:'收缩窗口',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'最小化窗口',exact:true}).click();
 expect(modes).toEqual(['compact','restore','minimize']);
});
