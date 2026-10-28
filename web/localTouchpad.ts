import {randomId} from './ids';

export interface InkStream extends EventTarget{close:()=>void}
export interface HelperSession{token:string;devices:{x_range:[number,number];y_range:[number,number];aspect_ratio?:number}[]}

// A top-level loopback window keeps hardware requests on the helper's origin.
// Cross-origin postMessage carries ink back even when public HTTP cannot fetch
// loopback resources. Every message is bound to the exact window and nonce.
export function connectLocalTouchpad(code:string):Promise<{session:HelperSession;source:InkStream}>{
 const origin='http://127.0.0.1:18765',nonce=randomId();
 const popup=window.open(origin+'/connect#'+new URLSearchParams({origin:location.origin,nonce,code}), 'MathMasterTouchpad-'+nonce,'popup,width=480,height=340');
 if(!popup)return Promise.reject(new Error('连接窗口被浏览器拦截，请允许弹出窗口后重试。'));
 return new Promise((resolve,reject)=>{
  let ready=false,closed=false;
  const source:InkStream=Object.assign(new EventTarget(),{close:()=>cleanup(true)});
  function cleanup(stop:boolean){
   if(closed)return;closed=true;clearTimeout(timeout);clearInterval(poll);window.removeEventListener('message',receive);
   if(stop&&!popup!.closed){popup!.postMessage({type:'stop',nonce},origin);setTimeout(()=>popup!.close(),3000);}
  }
  const timeout=setTimeout(()=>{if(!ready){cleanup(true);reject(new Error('助手连接超时，请先下载并运行 Windows 助手，再重新连接。'));}},12000);
  const poll=setInterval(()=>{if(popup.closed){cleanup(false);if(ready)source.dispatchEvent(new Event('error'));else reject(new Error('助手连接窗口已关闭。'));}},500);
  function receive(event:MessageEvent){
   if(event.origin!==origin||event.source!==popup||event.data?.nonce!==nonce||closed)return;
   const data=event.data;
   if(data.type==='ready'&&!ready){ready=true;clearTimeout(timeout);resolve({session:data.session,source});}
   else if(data.type==='ink'&&ready)source.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(data.event)}));
   else if(data.type==='error'){if(ready){source.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'error',message:data.message})}));}else{cleanup(true);reject(new Error(data.message||'助手连接失败'));}}
  }
  window.addEventListener('message',receive);
 });
}
