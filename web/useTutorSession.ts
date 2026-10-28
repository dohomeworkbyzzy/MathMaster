import {randomId} from './ids';
import {useEffect,useRef,useState} from 'react';
import {api,json,userStorageKey} from './types';

type Turn={id:string;request_id?:string;user_text:string;status:string;error:string;message:string};
type View={id:string;version:number;busy:boolean;stale:boolean;turns:Turn[]};
type Pending={sid:string;request_id:string;text:string;version:number};
function stored(key:string):Pending|null{
 try{const p=JSON.parse(localStorage.getItem(key)||'null');return p&&typeof p.sid==='string'&&typeof p.request_id==='string'&&typeof p.text==='string'&&Number.isInteger(p.version)&&p.version>=0?p:null;}catch{return null;}
}
async function request<T>(path:string,options?:RequestInit):Promise<T>{
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
 try{return await api<T>(path,{...options,signal:controller.signal});}
 catch(e){if(controller.signal.aborted)throw new Error('连接后台超时');throw e;}
 finally{clearTimeout(timer);}
}

export function useTutorSession<T extends View>(qid:string,revision:string){
 const draftKey=userStorageKey('mathmaster-ai-input-'+qid),pendingKey=userStorageKey('mathmaster-ai-pending-'+qid);
 const [input,setInput]=useState(()=>localStorage.getItem(draftKey)||'');
 const [pending,setPending]=useState<Pending|null>(()=>stored(pendingKey));
 const [session,stateSession]=useState<T|null>(null),[error,setError]=useState(''),[syncError,setSyncError]=useState('');
 const [sending,stateSending]=useState(false),[refreshing,setRefreshing]=useState(false),[clock,setClock]=useState(Date.now());
 const current=useRef<T|null>(null),receipt=useRef(pending),alive=useRef(true),locked=useRef(false);
 const read=useRef<{sid:string;promise:Promise<T>}|null>(null);
 const generation=useRef(0);
 const draft=useRef(input);draft.current=input;
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{localStorage.setItem(draftKey,input);},[input,draftKey]);
 function savePending(p:Pending|null){
  receipt.current=p;if(p)localStorage.setItem(pendingKey,JSON.stringify(p));else localStorage.removeItem(pendingKey);
  if(alive.current)setPending(p);
 }
 function setSession(next:T){
  if(!alive.current)return;
  const old=current.current,a=old?.turns.at(-1),b=next.turns.at(-1);
  if(old&&old.id!==next.id)return;
  // A slow poll must not replace a newer receipt or turn with an older snapshot.
  if(old?.id===next.id&&(next.version<old.version||next.turns.length<old.turns.length||(a?.id===b?.id&&a?.status!=='running'&&b?.status==='running')))return;
  current.current=next;stateSession(next);setSyncError('');setClock(Date.now());
  const p=receipt.current,t=p?.sid===next.id?next.turns.find(t=>t.request_id===p.request_id):undefined;
  if(t&&t.status!=='running'){
   if(t.status==='complete'){setInput(value=>value.trim()===p!.text?'':value);setError('');}
   else setError(t.error||'本轮未完成，输入已保留。');
   savePending(null);
  }else if(t)setError('');
 }
 async function fetchView(sid:string):Promise<T>{
  if(read.current?.sid===sid)return read.current.promise;
  const promise=request<T>('/api/ai/sessions/'+sid);
  const epoch=generation.current;
  read.current={sid,promise};if(alive.current)setRefreshing(true);
  try{const next=await promise;if(epoch===generation.current)setSession(next);return next;}
  finally{if(read.current?.promise===promise){read.current=null;if(alive.current)setRefreshing(false);}}
 }
 useEffect(()=>{
  let live=true;generation.current++;current.current=null;stateSession(null);setError('');
  const p=receipt.current;
  (p?request<T>('/api/ai/sessions/'+p.sid):request<T>('/api/questions/'+qid+'/ai',json({})))
   .then(s=>{if(live)setSession(s);}).catch(e=>{if(live)setSyncError((e as Error).message);});
  return()=>{live=false;};
 },[qid,revision]);
 async function refresh(){
  try{
   const sid=receipt.current?.sid||current.current?.id;
   if(sid)return await fetchView(sid);
   const next=await request<T>('/api/questions/'+qid+'/ai',json({}));setSession(next);return next;
  }catch(e){if(alive.current)setSyncError((e as Error).message);return null;}
 }
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{
  if(!session&&!pending)return;
  const poll=()=>{if(document.visibilityState!=='hidden')void refreshRef.current();};
  const timer=setInterval(poll,session?.busy||pending?1000:5000);
  window.addEventListener('focus',poll);document.addEventListener('visibilitychange',poll);
  return()=>{clearInterval(timer);window.removeEventListener('focus',poll);document.removeEventListener('visibilitychange',poll);};
 },[session?.id,session?.busy,pending?.request_id]);
 useEffect(()=>{
  if(!session?.busy&&!pending&&!sending)return;
  const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);
 },[session?.busy,pending?.request_id,sending]);
 async function post(p:Pending){
  try{const next=await request<T>('/api/ai/sessions/'+p.sid+'/turns',json({text:p.text,request_id:p.request_id,version:p.version}));setSession(next);}
  catch(e){
   if(!alive.current)return;
   setError('尚未确认发送结果：'+(e as Error).message+'。正在核对后台记录，请勿重复输入。');
   await refresh();
  }
 }
 async function send(text=input){
  const s=current.current;
  if(!s||s.busy||s.stale||locked.current||receipt.current||!text.trim())return;
  locked.current=true;stateSending(true);setError('');
  const requestId=randomId();
  const p={sid:s.id,request_id:requestId,text:text.trim(),version:s.version};
  try{savePending(p);if(draft.current.trim()!==p.text)setInput(p.text);await post(p);}
  finally{locked.current=false;if(alive.current)stateSending(false);}
 }
 async function retryPending(){
  if(locked.current||!receipt.current)return;
  locked.current=true;stateSending(true);
  try{
   const p=receipt.current,next=await fetchView(p.sid);
   if(next.turns.some(t=>t.request_id===p.request_id))return;
   if(next.stale){setError('题目已更新，先核对旧请求结果，再重新打开当前题目。');return;}
   if(next.busy){setError('后台正在处理另一条消息，请先等待结果。');return;}
   const sameRequest={...p,version:next.version};savePending(sameRequest);await post(sameRequest);
  }catch(e){if(alive.current)setSyncError((e as Error).message);}
  finally{locked.current=false;if(alive.current)stateSending(false);}
 }
 async function reopen(){
  if(locked.current||current.current?.busy)return;
  try{const next=await request<T>('/api/questions/'+qid+'/ai',json({}));savePending(null);current.current=null;setSession(next);setError('');}
  catch(e){if(alive.current)setSyncError((e as Error).message);}
 }
 return {session,setSession,input,setInput,pending,sending,error,setError,syncError,refreshing,refresh,retryPending,send,reopen,clock};
}
