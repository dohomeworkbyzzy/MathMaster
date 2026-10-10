import {useEffect,useRef,useState,type RefObject,type CSSProperties} from 'react';
import {createPortal} from 'react-dom';
import {api,json} from './types';

export interface InkPoint{x:number;y:number}
export type InkStroke=InkPoint[];
type NativeEvent={type:string;down?:boolean;id?:number;x?:number;y?:number;screen_x?:number;screen_y?:number;message?:string};
type Session={token:string;devices:{x_range:[number,number];y_range:[number,number];aspect_ratio?:number}[]};

// Uniform scaling preserves the geometry of fractions, radicals, and matrix brackets.
export function placeInk(strokes:InkStroke[],center:InkPoint,width:number,ratio:number):InkStroke[]{
 const height=width/ratio;
 const x=Math.max(width/2,Math.min(800-width/2,center.x));
 const y=Math.max(height/2,center.y);
 return strokes.map(line=>line.map(p=>({x:x+(p.x-.5)*width,y:y+(p.y-.5)*height})));
}
function path(line:InkStroke,width:number,height:number){return line.map((p,i)=>(i?'L':'M')+(p.x*width).toFixed(2)+' '+(p.y*height).toFixed(2)).join(' ')+(line.length===1?' l.2 .2':'');}
function previewBox(mouse:InkPoint,ratio:number,requested:number){
 const width=Math.max(60,Math.min(requested,window.innerWidth-24,Math.max(60,window.innerHeight-130)*ratio)),height=width/ratio;
 return {width,height,left:Math.max(12,Math.min(window.innerWidth-width-12,mouse.x-width/2)),top:Math.max(88,Math.min(window.innerHeight-height-12,mouse.y-height/2))};
}

export function TouchpadInk({canvas,onCommit}:{canvas:RefObject<HTMLCanvasElement|null>;onCommit:(strokes:InkStroke[])=>void}){
 const [active,setActive]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [ratio,setRatio]=useState(1.65),[width,setWidth]=useState(140);
 const [previewSize,setPreviewSize]=useState(()=>{const saved=Number(localStorage.getItem('mathmaster-pad-preview-width'));return saved>=200&&saved<=1000?saved:420;});
 const [,resizeView]=useState(0);
 const [mouse,setMouse]=useState({x:window.innerWidth/2,y:window.innerHeight/2});
 const [lines,setLines]=useState<InkStroke[]>([]),[ghost,setGhost]=useState<{lines:InkStroke[];left:number;top:number;width:number;height:number;dx:number;dy:number;scale:number}|null>(null);
 const pending=useRef<InkStroke[]>([]),stroke=useRef<InkStroke>([]),identity=useRef<number|null>(null);
 const anchor=useRef<InkPoint>({x:160,y:90});
 const stream=useRef<EventSource|null>(null),token=useRef<string|null>(null),disposed=useRef(false),live=useRef(false);
 const commitHandler=useRef(onCommit);commitHandler.current=onCommit;
 const params=useRef({ratio,width,previewSize});params.current={ratio,width,previewSize};
 const mouseRef=useRef(mouse);mouseRef.current=mouse;
 const lastTouch=useRef(0),ghostTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
 function show(){setLines([...pending.current,...(stroke.current.length?[stroke.current]:[])]);}
 function lift(){if(stroke.current.length)pending.current.push(stroke.current);stroke.current=[];identity.current=null;show();}
 function commit(){
  lift();if(!pending.current.length)return;
  const placed=placeInk(pending.current,anchor.current,params.current.width,params.current.ratio);
  const rect=canvas.current?.getBoundingClientRect();
  if(rect){
   const box=previewBox(mouseRef.current,params.current.ratio,params.current.previewSize),scale=rect.width/800;
   const target=placeInk([[{x:0,y:0}]],anchor.current,params.current.width,params.current.ratio)[0][0];
   setGhost({lines:pending.current,...box,dx:rect.left+target.x*scale-box.left,dy:rect.top+target.y*scale-box.top,scale:params.current.width*scale/box.width});
   if(ghostTimer.current)clearTimeout(ghostTimer.current);ghostTimer.current=setTimeout(()=>setGhost(null),300);
  }
  pending.current=[];stroke.current=[];setLines([]);commitHandler.current(placed);
 }
 function stop(save=true){
  if(save)commit();
  live.current=false;stream.current?.close();stream.current=null;
  if(token.current){const current=token.current;token.current=null;fetch('/api/touchpad/stop',{...json({token:current}),headers:{'Content-Type':'application/json'},keepalive:true}).catch(()=>{});}
  setActive(false);
 }
 const stopRef=useRef(stop);stopRef.current=stop;
 useEffect(()=>{const resized=()=>resizeView(v=>v+1);window.addEventListener('resize',resized);return()=>window.removeEventListener('resize',resized);},[]);
 useEffect(()=>{if(!active)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{document.body.style.overflow=previous;};},[active]);
 useEffect(()=>{
  disposed.current=false;
  const leave=()=>stopRef.current();
  const hide=()=>{if(document.hidden)leave();};
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'&&live.current){event.preventDefault();leave();}};
  window.addEventListener('blur',leave);window.addEventListener('pagehide',leave);
  document.addEventListener('visibilitychange',hide);window.addEventListener('keydown',key);
  return()=>{disposed.current=true;stopRef.current();if(ghostTimer.current)clearTimeout(ghostTimer.current);window.removeEventListener('blur',leave);window.removeEventListener('pagehide',leave);document.removeEventListener('visibilitychange',hide);window.removeEventListener('keydown',key);};
 },[]);
 async function start(){
  setBusy(true);setError('');
  try{
   const session=await api<Session>('/api/touchpad/start',json({}));token.current=session.token;
   if(disposed.current){stop(false);return;}
   const device=session.devices[0],r=device.aspect_ratio??(device.x_range[1]-device.x_range[0])/(device.y_range[1]-device.y_range[0]);
   setRatio(r);params.current.ratio=r;
   const rect=canvas.current?.getBoundingClientRect();
   if(rect){anchor.current={x:Math.min(400,anchor.current.x),y:Math.max(80,anchor.current.y)};const p={x:rect.left+anchor.current.x*rect.width/800,y:rect.top+anchor.current.y*rect.width/800};mouseRef.current=p;setMouse(p);}
   pending.current=[];stroke.current=[];identity.current=null;setLines([]);setActive(true);live.current=true;
   const source=new EventSource('/api/touchpad/events?token='+encodeURIComponent(session.token));stream.current=source;
   source.onmessage=message=>{
    if(!live.current)return;
    let event:NativeEvent;try{event=JSON.parse(message.data);}catch{return;}
    if(event.type==='contact'){
     lastTouch.current=performance.now();
     if(!event.down){lift();return;}
     if(typeof event.x!=='number'||typeof event.y!=='number'||!Number.isFinite(event.x)||!Number.isFinite(event.y))return;
     if(identity.current!==null&&identity.current!==event.id)lift();
     identity.current=event.id??0;
     if(stroke.current.length>=10000||pending.current.length>=200){commit();return;}
     stroke.current.push({x:Math.max(0,Math.min(1,event.x)),y:Math.max(0,Math.min(1,event.y))});show();
    }else if(event.type==='mouse'){
     // Only a hardware mouse event commits. Browser pointermove from the pad is ignored.
     commit();
     const x=(event.screen_x??window.screenX)-window.screenX;
     const y=(event.screen_y??window.screenY)-window.screenY-(window.outerHeight-window.innerHeight);
     mouseRef.current={x,y};setMouse({x,y});
     const box=canvas.current?.getBoundingClientRect();
     if(box&&x>=box.left&&x<=box.right&&y>=box.top&&y<=box.bottom)anchor.current={x:(x-box.left)*800/box.width,y:(y-box.top)*800/box.width};
    }else if(event.type==='pause')stopRef.current();
    else if(event.type==='error'){setError(event.message||'原始触控板连接已断开。');stopRef.current();}
   };
   source.onerror=()=>{if(live.current){setError('原始触控板连接已断开，请重新开启。');stopRef.current();}};
  }catch(e){setError((e as Error).message);stop(false);}
  finally{if(!disposed.current)setBusy(false);}
 }
 const {width:previewWidth,height:previewHeight,left,top}=previewBox(mouse,ratio,previewSize);
 return <>
  <button className="trackpad-toggle" aria-label="触控板书写" aria-pressed={active} disabled={busy} title="读取触控板绝对坐标，移动外接鼠标收笔" onClick={()=>active?stop():start()}>{busy?'连接中…':'触控板书写'}</button>
  {error&&<span className="touchpad-error" role="alert">{error}</span>}
  {active&&createPortal(<div className="touchpad-overlay" role="dialog" aria-label="触控板放大书写区">
   <div className="touchpad-controls" onPointerDownCapture={e=>{if(performance.now()-lastTouch.current<300)e.preventDefault();}}><span>触控板 · Esc 收笔</span><label>书写区<input aria-label="书写区大小" type="range" min="200" max="1000" step="20" value={previewSize} onChange={e=>{const size=Number(e.target.value);setPreviewSize(size);localStorage.setItem('mathmaster-pad-preview-width',String(size));}}/><output>{Math.round(previewWidth)}px</output></label><label>收笔<select aria-label="收笔大小" value={width} onChange={e=>{commit();setWidth(Number(e.target.value));}}><option value={80}>小</option><option value={140}>中</option><option value={220}>大</option></select></label><button onClick={()=>{if(performance.now()-lastTouch.current>300)stop();}}>完成</button></div>
   <svg className="touchpad-writing" aria-label="放大笔迹" width={previewWidth} height={previewHeight} style={{left,top}} viewBox={`0 0 ${previewWidth} ${previewHeight}`}>
    <path className="touchpad-center" d={`M${previewWidth/2-6} ${previewHeight/2}h12 M${previewWidth/2} ${previewHeight/2-6}v12`}/>
    {lines.map((line,i)=><path key={i} d={path(line,previewWidth,previewHeight)} fill="none" stroke="#222" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>)}
   </svg>
  </div>,document.body)}
  {ghost&&createPortal(<svg className="touchpad-stamp" style={{left:ghost.left,top:ghost.top,'--stamp-x':ghost.dx+'px','--stamp-y':ghost.dy+'px','--stamp-scale':ghost.scale} as CSSProperties} width={ghost.width} height={ghost.height} viewBox={`0 0 ${ghost.width} ${ghost.height}`}>{ghost.lines.map((line,i)=><path key={i} d={path(line,ghost.width,ghost.height)} fill="none" stroke="#333" strokeWidth="2.5" strokeLinecap="round"/>)}</svg>,document.body)}
 </>;
}
