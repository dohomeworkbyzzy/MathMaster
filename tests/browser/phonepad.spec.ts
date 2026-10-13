import {test,expect} from '@playwright/test';

test('real phone ink channel maps its complete surface to the large mouse range and saves',async({page,request})=>{
 const number='PHONE-PAD-'+Date.now();
 const {id}=await (await request.post('/api/questions',{data:{number,text:'手机草稿范围验收',confirmed:true}})).json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/phonepad/start'));
 const streamPromise=page.waitForResponse(r=>r.url().includes('/api/phonepad/events?'));
 await page.getByRole('button',{name:'手机书写',exact:true}).click();
 const response=await responsePromise;expect(response.ok()).toBeTruthy();const session=await response.json();
 await streamPromise;
 const ws=new WebSocket('ws://127.0.0.1:'+session.port+'/ink');
 try{
  await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Phone pairing timed out')),8000);ws.onopen=()=>ws.send(JSON.stringify({type:'hello',code:session.code}));ws.onerror=reject;ws.onmessage=e=>{const event=JSON.parse(String(e.data));if(event.type==='ready'){clearTimeout(timer);resolve();}else if(event.type==='error'){clearTimeout(timer);reject(new Error(event.message));}};});
  ws.send(JSON.stringify({type:'surface',ratio:2}));
  await expect(page.getByRole('status').filter({hasText:'手机已连接'})).toBeVisible();
  const canvas=(await page.getByLabel('电子草稿画布').boundingBox())!;
  await page.mouse.move(canvas.x+canvas.width*.5,canvas.y+100);
  const target=page.getByLabel('草稿落笔范围'),preview=page.getByLabel('放大笔迹');
  await expect(target).toBeVisible();
  const box=(await target.boundingBox())!;
  expect(box.width).toBeGreaterThan(220);
  expect(box.width/box.height).toBeCloseTo(2,3);
  expect((await preview.boundingBox())!.width).toBeCloseTo(box.width,1);
  ws.send(JSON.stringify({type:'contact',down:true,x:0,y:0}));
  ws.send(JSON.stringify({type:'contact',down:true,x:1,y:1}));
  ws.send(JSON.stringify({type:'contact',down:false}));
  await expect(preview.locator('path')).toHaveCount(1);
  await page.screenshot({path:'test-results/phonepad-large-range.png'});
  await page.mouse.move(canvas.x+canvas.width*.6,canvas.y+110);
  await expect.poll(async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length).toBe(1);
  const saved=JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt.draft)[0];
  expect(saved[1].x-saved[0].x).toBeCloseTo(box.width*800/canvas.width,1);
  expect((saved[1].x-saved[0].x)/(saved[1].y-saved[0].y)).toBeCloseTo(2,4);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toHaveCount(0);
 }finally{ws.close();}
});
