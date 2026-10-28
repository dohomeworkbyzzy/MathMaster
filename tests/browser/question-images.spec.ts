import {test,expect} from '@playwright/test';

test('all question images stretch to fill when the window and divider shrink',async({page,request})=>{
 const number='IMAGE-FIT-'+Date.now();
 const {id}=await (await request.post('/api/questions',{data:{number,text:'题图缩放验收\n'+('识别文字，仅作参考。\n'.repeat(20)),confirmed:true}})).json();
 // Explicit image fixtures: exercise the real practice page without changing personal paper data.
 const dimensions=[[800,1800],[1500,600],[10000,350]];
 const images=dimensions.map((_,i)=>`image-fit-${i}.svg`);
 await page.route('**/api/questions/'+id,async route=>{
  const response=await route.fetch(),question=await response.json();
  await route.fulfill({response,json:{...question,images}});
 });
 for(const [i,[width,height]] of dimensions.entries())await page.route('**/api/files/'+images[i],route=>route.fulfill({contentType:'image/svg+xml',body:
  `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="white" stroke="black" stroke-width="8"/><text x="20" y="50" font-size="32">Question ${i+1}</text><text x="20" y="${height-20}" font-size="32">End of question ${i+1}</text></svg>`}));
 async function openQuestion(){
  await page.getByRole('button',{name:'本地题库',exact:true}).click();
  await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 }
 await page.goto('/');await openQuestion();
 const question=page.getByRole('region',{name:'题目区'});
 async function checkComplete(){
  await expect.poll(()=>question.evaluate(el=>{
   const bounds=el.getBoundingClientRect(),area=el.querySelector('.question-images')!.getBoundingClientRect();
   const images=[...el.querySelectorAll<HTMLImageElement>('.question-image')];
   return images.length===3&&images.every(image=>{
    const rect=image.getBoundingClientRect();
    return image.naturalWidth>0&&rect.width>0&&rect.height>0&&
     Math.abs(rect.width-area.width)<.5&&getComputedStyle(image).objectFit==='fill'&&
     rect.top>=area.top-.5&&rect.bottom<=area.bottom+.5&&rect.left>=area.left-.5&&rect.right<=area.right+.5&&
     rect.top>=bounds.top&&rect.bottom<=bounds.bottom;
   })&&Math.abs(images[0].getBoundingClientRect().top-area.top)<.5&&
    Math.abs(images.at(-1)!.getBoundingClientRect().bottom-area.bottom)<.5&&el.scrollHeight<=el.clientHeight+1;
  })).toBeTruthy();
 }
 for(const viewport of [{width:1440,height:1000},{width:640,height:520},{width:480,height:420},{width:1000,height:640}]){
  await page.setViewportSize(viewport);await checkComplete();
  const paper=(await page.locator('.sketch-paper').boundingBox())!;
  expect(paper.height).toBeGreaterThan(90);expect(paper.y+paper.height).toBeLessThanOrEqual(viewport.height+1);
 }
 const originalHeight=(await page.getByAltText('题目原始截图 1').boundingBox())!.height;
 const divider=page.getByRole('separator',{name:'调整题目与草稿高度'});
 await divider.focus();await page.keyboard.press('ArrowUp');await page.keyboard.press('ArrowUp');
 await checkComplete();expect((await page.getByAltText('题目原始截图 1').boundingBox())!.height).toBeLessThan(originalHeight);
 await page.getByText('题目说明与识别文字',{exact:true}).click();await checkComplete();
 await page.getByRole('button',{name:'放大题图',exact:true}).click();
 await expect(page.getByRole('button',{name:'完整题图',exact:true})).toBeVisible();
 await expect.poll(()=>question.evaluate(el=>el.scrollHeight>el.clientHeight)).toBeTruthy();
 await page.getByRole('button',{name:'完整题图',exact:true}).click();await checkComplete();
 const popup=page.waitForEvent('popup');await page.getByAltText('题目原始截图 1').click();
 const original=await popup;await expect(original).toHaveURL(new RegExp('/api/files/'+images[0]));await original.close();
 await page.route('**/api/files/'+images[2],route=>route.fulfill({status:404,body:'Missing fixture'}));
 await page.reload();await openQuestion();await expect(page.locator('.question-image-errors')).toContainText('题图加载失败');
 await expect(page.getByAltText('题目原始截图 1')).toBeVisible();
 await expect.poll(()=>question.evaluate(el=>el.scrollHeight<=el.clientHeight+1)).toBeTruthy();
});
