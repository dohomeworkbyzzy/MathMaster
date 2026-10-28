import {test,expect} from '@playwright/test';

async function exercise(page:any,request:any,prefix:string){
 const number=prefix+Date.now();
 const response=await request.post('/api/questions',{data:{number,text:'触控板草稿验收题',confirmed:true}});
 const {id}=await response.json();
 await page.goto('/');await page.getByRole('button',{name:'本地题库',exact:true}).click();
 await page.getByLabel('搜索题库').fill(number);await page.locator('.question-card').getByRole('button',{name:'开始练习'}).click();
 return id;
}

test('unavailable native input reports a real error; conventional mouse ink still saves',async({page,request})=>{
 // Explicit error fixture: this test must not depend on a CI machine's physical pad.
 await page.route('**/api/touchpad/start',route=>route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:'未发现提供绝对坐标的 Windows Precision Touchpad。'})}));
 const id=await exercise(page,request,'MOUSE-');
 const canvas=page.getByLabel('电子草稿画布'),box=(await canvas.boundingBox())!;
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('未发现提供绝对坐标');
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toHaveCount(0);
 await page.mouse.move(box.x+40,box.y+50);await page.mouse.down();
 await page.mouse.move(box.x+95,box.y+90,{steps:8});await page.mouse.up();
 await expect.poll(async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length).toBe(1);
 await page.getByRole('button',{name:'撤销笔画'}).click();
 await expect.poll(async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length).toBe(0);
});

test('absolute contact fixtures lift separately, ignore cursor moves, shrink on hardware mouse and save',async({page,request})=>{
 // Synthetic native event stream for browser acceptance; never used by production.
 await page.addInitScript(()=>{
  class FixtureStream extends EventTarget {
   onmessage=(event:{data:string})=>this.dispatchEvent(new MessageEvent('message',{data:event.data}));
   constructor(){super();(window as any).__pad=this;}
   close(){(window as any).__padClosed=true;}
  }
  (window as any).EventSource=FixtureStream;
 });
 await page.route('**/api/touchpad/start',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({token:'test-session-owner-token-123456',devices:[{x_range:[0,3684],y_range:[0,2176],aspect_ratio:457/281}]})}));
 await page.route('**/api/touchpad/stop',route=>route.fulfill({contentType:'application/json',body:'{"stopped":true}'}));
 const id=await exercise(page,request,'RAW-PAD-');
 const count=async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]').length;
 const emit=async(events:any[])=>page.evaluate(events=>{for(const event of events)(window as any).__pad.onmessage({data:JSON.stringify(event)});},events);
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toBeVisible();
 await expect(page.getByLabel('草稿落笔范围')).toHaveCount(0);
 await emit([{type:'contact',down:true,id:0,x:.2,y:.2},{type:'contact',down:false}]);
 expect(await count()).toBe(0); // Starting on the toolbar never guesses a destination.
 const firstTarget=await page.getByLabel('电子草稿画布').evaluate(el=>{const box=el.getBoundingClientRect();return {type:'mouse',screen_x:window.screenX+box.left+box.width*.2,screen_y:window.screenY+window.outerHeight-window.innerHeight+box.top+box.width*90/800};});
 await emit([firstTarget]);
 await expect(page.getByLabel('草稿落笔范围')).toBeVisible();
 const preview=page.getByLabel('放大笔迹');
 expect((await preview.boundingBox())!.width).toBeCloseTo(420,0);
 await page.getByLabel('书写区大小').fill('240');
 await expect.poll(async()=>(await preview.boundingBox())!.width).toBeCloseTo(240,0);
 await emit([{type:'contact',down:true,id:1,x:.1,y:.2},{type:'contact',down:true,id:1,x:.3,y:.4},{type:'contact',down:false},{type:'contact',down:true,id:2,x:.5,y:.4},{type:'contact',down:true,id:2,x:.8,y:.4},{type:'contact',down:false}]);
 await expect(page.getByLabel('放大笔迹').locator('path:not(.touchpad-center)')).toHaveCount(2);
 await page.mouse.move(1000,600,{steps:6}); // OS cursor events from pad must not commit.
 expect(await count()).toBe(0);
 await expect(page.getByLabel('草稿落笔范围')).toBeVisible(); // Browser moves don't move the target.
 const destination=await page.getByLabel('电子草稿画布').evaluate(el=>{const box=el.getBoundingClientRect();return {type:'mouse',screen_x:window.screenX+box.left+box.width*.6,screen_y:window.screenY+window.outerHeight-window.innerHeight+box.top+box.width*.15};});
 await emit([destination]);
 await expect.poll(count).toBe(2);
 let saved=JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt.draft);
 expect(saved[0][0].x).toBeCloseTo(104,4);
 expect(saved[0][1].x-saved[0][0].x).toBeCloseTo(28,4);
 expect(saved[0][1].y-saved[0][0].y).toBeCloseTo(28/(457/281),4);
 expect(saved[1][0].x).toBeCloseTo(160,4); // Separate stroke, same absolute surface.
 await expect(page.getByLabel('放大笔迹').locator('path:not(.touchpad-center)')).toHaveCount(0);
 await emit([{type:'contact',down:true,id:3,x:.2,y:.3},{type:'contact',down:true,id:3,x:.4,y:.4},{type:'contact',down:false}]);
 await page.keyboard.press('Escape');
 await expect(page.getByRole('dialog',{name:'触控板放大书写区'})).toHaveCount(0);
 expect(await page.evaluate(()=>localStorage.getItem('mathmaster-pad-preview-width'))).toBe('240');
 await expect.poll(count).toBe(3);
 saved=JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt.draft);
 expect(saved[2][0].x).toBeCloseTo(438,3); // New mouse position reanchors the next group.
 await page.getByRole('button',{name:'返回题库'}).click();
 await page.locator('.question-card').getByRole('button',{name:/开始练习|继续作答/}).click();
 expect(await count()).toBe(3);
 await page.getByRole('button',{name:'清空草稿'}).click();await expect.poll(count).toBe(0);
});

test('mouse selects a visible bounded destination; outside paper ignores ink and commits keep the old destination',async({page,request})=>{
 await page.addInitScript(()=>{
  class Stream extends EventTarget {onmessage=(event:{data:string})=>this.dispatchEvent(new MessageEvent('message',{data:event.data}));constructor(){super();(window as any).__pad=this;}close(){}}
  (window as any).EventSource=Stream;
 });
 await page.route('**/api/touchpad/start',route=>route.fulfill({json:{token:'bounded-native-test-session-token',devices:[{x_range:[0,1000],y_range:[0,600],aspect_ratio:1.65}]}}));
 await page.route('**/api/touchpad/stop',route=>route.fulfill({json:{stopped:true}}));
 const id=await exercise(page,request,'BOUND-PAD-');
 const emit=async(events:any[])=>page.evaluate(events=>{for(const event of events)(window as any).__pad.onmessage({data:JSON.stringify(event)});},events);
 const saved=async()=>JSON.parse((await (await request.get('/api/questions/'+id)).json()).attempt?.draft||'[]');
 await page.getByRole('button',{name:'触控板书写',exact:true}).click();
 await page.getByLabel('落笔范围大小').selectOption('220');
 const corner=await page.getByLabel('电子草稿画布').evaluate(el=>{const canvas=el.getBoundingClientRect(),paper=el.closest('.sketch-paper')!.getBoundingClientRect();return {type:'mouse',screen_x:window.screenX+Math.min(canvas.right,paper.right)-4,screen_y:window.screenY+window.outerHeight-window.innerHeight+Math.min(canvas.bottom,paper.bottom,innerHeight)-4};});
 await emit([corner]);
 const target=(await page.getByLabel('草稿落笔范围').boundingBox())!;
 const bounds=await page.getByLabel('电子草稿画布').evaluate(el=>{const canvas=el.getBoundingClientRect(),paper=el.closest('.sketch-paper')!.getBoundingClientRect();return {left:Math.max(canvas.left,paper.left),top:Math.max(canvas.top,paper.top),right:Math.min(canvas.right,paper.right),bottom:Math.min(canvas.bottom,paper.bottom,innerHeight),scale:canvas.width/800,canvasLeft:canvas.left,canvasTop:canvas.top};});
 expect(target.x).toBeGreaterThanOrEqual(bounds.left);
 expect(target.y).toBeGreaterThanOrEqual(bounds.top);
 expect(target.x+target.width).toBeLessThanOrEqual(bounds.right);
 expect(target.y+target.height).toBeLessThanOrEqual(bounds.bottom);
 await emit([{type:'contact',down:true,id:1,x:0,y:0},{type:'contact',down:true,id:1,x:1,y:1},{type:'contact',down:false}]);
 await page.screenshot({path:'artifacts/touchpad-target.png'});
 const outside=await page.evaluate(()=>({type:'mouse',screen_x:window.screenX+5,screen_y:window.screenY+window.outerHeight-window.innerHeight+5}));
 await emit([outside]);
 await expect.poll(async()=>(await saved()).length).toBe(1);
 const ink=(await saved())[0];
 // CSS rectangles round to layout subpixels; compare in screen pixels while
 // independently checking the stored uniform scale at mathematical precision.
 expect(Math.abs(bounds.canvasLeft+ink[0].x*bounds.scale-target.x)).toBeLessThan(.05);
 expect(Math.abs(bounds.canvasTop+ink[0].y*bounds.scale-target.y)).toBeLessThan(.05);
 expect(Math.abs((ink[1].x-ink[0].x)*bounds.scale-target.width)).toBeLessThan(.05);
 expect(Math.abs((ink[1].y-ink[0].y)*bounds.scale-target.height)).toBeLessThan(.05);
 expect(ink[1].x-ink[0].x).toBeCloseTo(220,9);
 expect(ink[1].y-ink[0].y).toBeCloseTo(220/1.65,9);
 expect(ink[1].x).toBeLessThanOrEqual(800);
 expect(ink[1].y).toBeLessThanOrEqual((bounds.bottom-bounds.canvasTop)/bounds.scale);
 await expect(page.getByLabel('草稿落笔范围')).toHaveCount(0);
 await emit([{type:'contact',down:true,id:2,x:.1,y:.1},{type:'contact',down:true,id:2,x:.9,y:.9},{type:'contact',down:false}]);
 expect((await saved()).length).toBe(1);
 await page.keyboard.press('Escape');await page.reload();
 expect((await saved()).length).toBe(1);
});
