import {useCallback,useEffect,useRef,useState} from 'react';
import {Download,Eraser,Highlighter,PencilLine,Redo2,RotateCcw,Trash2} from 'lucide-react';
import {api,json,userStorageKey} from './types';
import {randomId} from './ids';
import './QuestionAnnotations.css';

type Point={x:number;y:number};
type Tool='pen'|'highlight'|'erase';
export interface AnnotationStroke{id:string;image:string;tool:'pen'|'highlight';color:string;width:number;points:Point[]}
interface Document{version:number;strokes:AnnotationStroke[];updated_at?:string|null}
const colors=[['#ff6b6b','红色'],['#4dabf7','蓝色'],['#ffd43b','黄色'],['#51cf66','绿色']];
const finishEvent='mathmaster-annotation-flush';
export function finishAnnotations(){window.dispatchEvent(new Event(finishEvent));}

export function useQuestionAnnotations(qid:string,hasImages:boolean,notify:(s:string)=>void){
 const [strokes,setStrokes]=useState<AnnotationStroke[]>([]),[ready,setReady]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('读取标注中…');
 const [recovery,setRecovery]=useState<Document|null>(null);
 const [enabled,setEnabled]=useState(false),[tool,setTool]=useState<Tool>('pen'),[color,setColor]=useState('#ff6b6b'),[width,setWidth]=useState(3);
 const [past,setPast]=useState<AnnotationStroke[][]>([]),[future,setFuture]=useState<AnnotationStroke[][]>([]);
 const history=useRef<{past:AnnotationStroke[][];future:AnnotationStroke[][]}>({past:[],future:[]});
 const latest=useRef(strokes),version=useRef(0),saved=useRef('[]'),loaded=useRef(false),mounted=useRef(true),chain=useRef(Promise.resolve());
 const key=userStorageKey('mathmaster-question-annotations-'+qid+'-'+(sessionStorage.getItem('mathmaster-tab-id')||'tab'));
 const cache=useCallback((value:AnnotationStroke[])=>{try{localStorage.setItem(key,JSON.stringify({version:version.current,strokes:value}));}catch{notify('标注缓存已满，请及时下载标注并保存。');}},[key,notify]);
 useEffect(()=>{
  let live=true;mounted.current=true;
  if(!hasImages){setStatus('');return;}
  api<Document>('/api/questions/'+qid+'/annotations').then(doc=>{
   if(!live)return;version.current=doc.version;saved.current=JSON.stringify(doc.strokes);let initial=doc.strokes;
   try{const raw=localStorage.getItem(key);if(raw){const local=JSON.parse(raw) as Document;
    if(Number.isInteger(local.version)&&Array.isArray(local.strokes)&&local.strokes.every(s=>s&&typeof s.id==='string'&&typeof s.image==='string'&&colors.some(c=>c[0]===s.color)&&['pen','highlight'].includes(s.tool)&&Number.isFinite(s.width)&&s.width>=1&&s.width<=30&&Array.isArray(s.points)&&s.points.length>0&&s.points.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1))){
     if(JSON.stringify(local.strokes)===saved.current)localStorage.removeItem(key);
     else if(local.version===doc.version)initial=local.strokes;else setRecovery(local);
    }
   }}catch{}
   latest.current=initial;loaded.current=true;setStrokes(initial);setReady(true);setStatus(JSON.stringify(initial)===saved.current?'标注已保存':'标注待保存');
  }).catch(e=>{if(live){setError(e.message==='Not Found'?'服务器版本暂不支持题目标注，请更新服务程序并重启。':e.message);setStatus('标注读取失败');}});
  return()=>{live=false;mounted.current=false;};
 },[qid,hasImages,key]);
 const flush=useCallback(async()=>{
  if(!loaded.current)return;
  chain.current=chain.current.catch(()=>{}).then(async()=>{
   const snapshot=latest.current,encoded=JSON.stringify(snapshot);if(encoded===saved.current){if(mounted.current){setStatus('标注已保存');setError('');}return;}
   if(mounted.current)setStatus('保存标注中…');
   try{
    const result=await api<{version:number}>('/api/questions/'+qid+'/annotations',json({version:version.current,strokes:snapshot},'PUT'));
    version.current=result.version;saved.current=encoded;
    if(JSON.stringify(latest.current)===encoded)localStorage.removeItem(key);else cache(latest.current);
    if(mounted.current){setError('');setStatus(JSON.stringify(latest.current)===encoded?'标注已保存':'标注待保存');}
   }catch(e){cache(latest.current);if(mounted.current){setError((e as Error).message);setStatus('标注未同步 · 已保留本机副本');}throw e;}
  });await chain.current;
 },[qid,key,cache]);
 useEffect(()=>{if(!ready)return;const timer=setTimeout(()=>void flush().catch(e=>notify(e.message)),600);return()=>clearTimeout(timer);},[strokes,ready,flush,notify]);
 const flushRef=useRef(flush);flushRef.current=flush;
 useEffect(()=>()=>{finishAnnotations();void flushRef.current().catch(()=>{});},[]);
 function update(next:AnnotationStroke[]){latest.current=next;setStrokes(next);cache(next);setStatus('标注待保存');}
 function historyState(past:AnnotationStroke[][],future:AnnotationStroke[][]){history.current={past,future};setPast(past);setFuture(future);}
 function change(next:AnnotationStroke[]){const before=latest.current;if(JSON.stringify(next)===JSON.stringify(before))return;historyState([...history.current.past.slice(-19),before],[]);update(next);}
 function undo(){finishAnnotations();const {past,future}=history.current;if(!past.length)return;const before=latest.current,next=past[past.length-1];historyState(past.slice(0,-1),[before,...future]);update(next);}
 function redo(){finishAnnotations();const {past,future}=history.current;if(!future.length)return;const before=latest.current,next=future[0];historyState([...past,before],future.slice(1));update(next);}
 function download(){const url=URL.createObjectURL(new Blob([JSON.stringify({question_id:qid,version:version.current,strokes:recovery?.strokes||latest.current},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='题目标注-'+qid+'.json';a.click();URL.revokeObjectURL(url);}
 return {strokes,ready,error,status,recovery,enabled,tool,color,width,past,future,flush,change,undo,redo,download,
  toggle:()=>{finishAnnotations();setEnabled(v=>!v);},exit:()=>{finishAnnotations();setEnabled(false);},setTool:(t:Tool)=>{finishAnnotations();setTool(t);if(t==='highlight')setColor('#ffd43b');},setColor,setWidth,
  clear:()=>{finishAnnotations();change([]);},restore:()=>{if(recovery){change(recovery.strokes);setRecovery(null);}},retry:()=>void flush().catch(e=>notify(e.message))};
}
export type QuestionAnnotationController=ReturnType<typeof useQuestionAnnotations>;

export function AnnotationToolbar({controller:c}:{controller:QuestionAnnotationController}){
 return <>{c.enabled&&<div className="question-annotation-toolbar" role="toolbar" aria-label="题目标注工具">
  {([['pen',PencilLine,'画笔'],['highlight',Highlighter,'荧光笔'],['erase',Eraser,'橡皮擦']] as const).map(([tool,Icon,label])=><button key={tool} aria-label={label} aria-pressed={c.tool===tool} onClick={()=>c.setTool(tool)} title={label}><Icon size={14}/><span>{label}</span></button>)}
  <label>颜色<select aria-label="标注颜色" disabled={c.tool==='erase'} value={c.color} onChange={e=>c.setColor(e.target.value)}>{colors.map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
  <label>粗细<select aria-label="标注粗细" disabled={c.tool==='erase'} value={c.width} onChange={e=>c.setWidth(+e.target.value)}>{[2,3,5].map(w=><option key={w} value={w}>{w}</option>)}</select></label>
  <button aria-label="撤销标注" title="撤销标注" disabled={!c.past.length} onClick={c.undo}><RotateCcw size={14}/></button><button aria-label="重做标注" title="重做标注" disabled={!c.future.length} onClick={c.redo}><Redo2 size={14}/></button>
  <button aria-label="清空标注" title="清空标注，可撤销" disabled={!c.strokes.length} onClick={c.clear}><Trash2 size={14}/></button><button aria-label="下载标注" title="下载本题标注记录" onClick={c.download}><Download size={14}/></button>
  <span className="annotation-save-status" role="status">{c.status}</span>
 </div>}{(c.error||c.recovery)&&<div className="annotation-error" role="alert">{c.error||'发现未同步的旧标注，已保留服务器记录。'}{(c.recovery||c.strokes.length>0)&&<button onClick={c.download}>下载未同步标注</button>}{c.recovery?<button onClick={c.restore}>用旧标注替换当前标注</button>:c.ready?<button onClick={c.retry}>重试保存</button>:<span>请重新打开题目后重试读取。</span>}</div>}</>;
}

function distance(p:Point,a:Point,b:Point,w:number,h:number){
 const dx=(b.x-a.x)*w,dy=(b.y-a.y)*h,px=(p.x-a.x)*w,py=(p.y-a.y)*h;
 const t=Math.max(0,Math.min(1,(px*dx+py*dy)/(dx*dx+dy*dy||1)));return Math.hypot(px-t*dx,py-t*dy);
}
function path(stroke:AnnotationStroke){return stroke.points.map((p,i)=>(i?'L':'M')+(p.x*1000).toFixed(3)+' '+(p.y*1000).toFixed(3)).join(' ')+(stroke.points.length===1?' l.01 .01':'');}

export function AnnotationOverlay({image,index,controller:c}:{image:string;index:number;controller:QuestionAnnotationController}){
 const element=useRef<SVGSVGElement>(null),[current,setCurrent]=useState<AnnotationStroke|null>(null),[erased,setErased]=useState<Set<string>>(new Set());
 const gesture=useRef<{stroke:AnnotationStroke|null;erased:Set<string>;pointer:number}|null>(null);
 const controller=useRef(c);controller.current=c;
 function finish(){
  const g=gesture.current;if(!g)return;gesture.current=null;setCurrent(null);setErased(new Set());
  const c=controller.current;if(g.stroke)c.change([...c.strokes,g.stroke]);else if(g.erased.size)c.change(c.strokes.filter(s=>!g.erased.has(s.id)));
  if(element.current?.hasPointerCapture(g.pointer))element.current.releasePointerCapture(g.pointer);
 }
 const finishRef=useRef(finish);finishRef.current=finish;
 useEffect(()=>{
  const done=()=>finishRef.current(),hide=()=>{if(document.hidden)done();};
  window.addEventListener(finishEvent,done);window.addEventListener('mathmaster-cover',done);window.addEventListener('blur',done);document.addEventListener('visibilitychange',hide);
  return()=>{done();window.removeEventListener(finishEvent,done);window.removeEventListener('mathmaster-cover',done);window.removeEventListener('blur',done);document.removeEventListener('visibilitychange',hide);};
 },[]);
 function point(e:React.PointerEvent<SVGSVGElement>):Point{const r=e.currentTarget.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};}
 function erase(p:Point){
  const g=gesture.current,r=element.current?.getBoundingClientRect();if(!g||!r)return;
  for(const s of controller.current.strokes){if(s.image!==image||g.erased.has(s.id))continue;const radius=Math.max(8,s.width/2+4);
   if(s.points.some((a,i)=>distance(p,a,s.points[Math.min(i+1,s.points.length-1)],r.width,r.height)<=radius))g.erased.add(s.id);
  }setErased(new Set(g.erased));
 }
 function start(e:React.PointerEvent<SVGSVGElement>){
  if(!c.enabled||!c.ready||!e.isPrimary||e.button!==0)return;e.preventDefault();e.currentTarget.focus({preventScroll:true});e.currentTarget.setPointerCapture(e.pointerId);
  const p=point(e),stroke=c.tool==='erase'?null:{id:randomId(),image,tool:c.tool,color:c.color,width:c.tool==='highlight'?c.width*5:c.width,points:[p]};
  gesture.current={stroke,erased:new Set(),pointer:e.pointerId};if(stroke)setCurrent(stroke);else erase(p);
 }
 function move(e:React.PointerEvent<SVGSVGElement>){
  const g=gesture.current;if(!g||e.pointerId!==g.pointer)return;e.preventDefault();const p=point(e);
  if(g.stroke){if(g.stroke.points.length>=10000){finish();return;}g.stroke={...g.stroke,points:[...g.stroke.points,p]};setCurrent(g.stroke);}else erase(p);
 }
 const visible=c.strokes.filter(s=>s.image===image&&!erased.has(s.id));if(current)visible.push(current);
 return <svg ref={element} className={'question-annotation-overlay'+(c.enabled?' annotation-active':'')+(c.tool==='erase'?' annotation-eraser':'')} viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label={'题图标注层 '+(index+1)} tabIndex={c.enabled?0:-1}
  onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish} onContextMenu={e=>{if(c.enabled)e.preventDefault();}}
  onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();c.exit();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();if(e.shiftKey)c.redo();else c.undo();}}}>
  {visible.map(s=><path key={s.id} data-stroke-id={s.id} d={path(s)} stroke={s.color} strokeWidth={s.width} opacity={s.tool==='highlight'?.3:1} vectorEffect="non-scaling-stroke" fill="none" strokeLinecap="round" strokeLinejoin="round"/>)}
 </svg>;
}
