import {test,expect} from '@playwright/test';

test('implicit chain rule, point and history restore',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'求导',exact:true}).click();
 await page.getByLabel('求导模式').selectOption('implicit');
 await expect(page.getByLabel('导数阶数')).toHaveCount(0);
 await expect(page.getByLabel('混合偏导')).toHaveCount(0);
 await page.getByRole('button',{name:'文本表达式',exact:true}).click();
 await page.getByLabel('文本表达式',{exact:true}).fill('x^2+y^2=1');
 await page.getByLabel('自变量点坐标').fill('3/5');
 await page.getByLabel('因变量点坐标').fill('4/5');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await expect(page.locator('.verified-badge')).toContainText('验证通过');
 await expect(page.locator('.step summary').filter({hasText:'隐函数链式法则'})).toBeVisible();
 await expect(page.locator('.step summary').filter({hasText:'整理含导数的项'})).toBeVisible();
 await expect(page.locator('.conditions')).toContainText('C¹');
 await page.getByRole('button',{name:'计算历史',exact:true}).click();
 await page.locator('.history-item').first().click();
 await expect(page.getByLabel('求导模式')).toHaveValue('implicit');
 await expect(page.getByLabel('自变量点坐标')).toHaveValue('3/5');
 await expect(page.getByLabel('因变量点坐标')).toHaveValue('4/5');
 await page.getByLabel('自变量点坐标').fill('0');
 await page.getByLabel('因变量点坐标').fill('0');
 await page.getByLabel('文本表达式',{exact:true}).fill('y^3=x^3');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await expect(page.locator('.warnings')).toContainText('当前方法无法判定');
 await expect(page.locator('.answer-box')).toContainText('当前方法无法判定');
 await page.getByLabel('求导模式').selectOption('explicit');
 await expect(page.getByLabel('导数阶数')).toBeVisible();
 await page.getByLabel('文本表达式',{exact:true}).fill('sin(x^2)');
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await expect(page.locator('.answer-box')).toContainText('cos');
 await expect(page.locator('.verified-badge')).toContainText('验证通过');
});

test('formula input accepts an implicit equation',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'求导',exact:true}).click();
 await page.getByLabel('求导模式').selectOption('implicit');
 const field=page.locator('math-field');
 await field.evaluate(el=>{
  (el as HTMLElement & {value:string}).value='x^2+y^2=1';
  el.dispatchEvent(new Event('input',{bubbles:true}));
 });
 await page.getByRole('button',{name:'开始计算',exact:true}).click();
 await expect(page.locator('.verified-badge')).toContainText('验证通过');
 await expect(page.locator('.step summary').filter({hasText:'隐函数独立验证'})).toBeVisible();
});
