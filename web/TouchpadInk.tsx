import {useEffect,useRef,useState,type RefObject,type CSSProperties} from 'react';
import {createPortal} from 'react-dom';
import {api,json} from './types';

export interface InkPoint{x:number;y:number}
export type InkStroke=InkPoint[];
type NativeEvent={type:string;down?:boolean;id?:number;x?:number;y?:number;screen_x?:number;screen_y?:number;message?:string;ratio?:number};
type Session={token:string;code?:string;hosts?:string[];port?:number;devices:{x_range:[number,number];y_range:[number,number];aspect_ratio?:number}[]};
type Placement={center:InkPoint;width:number;ratio:number};
type Target=Placement&{left:number;top:number;screenWidth:number;screenHeight:number};

// Uniform scaling preserves the geometry of fractions, radicals, and matrix brackets.
export function placeInk(strokes:InkStroke[],center:InkPoint,width:number,ratio:number):InkStroke[]{
 const height=width/ratio;
 const x=Math.max(width/2,Math.min(800-width/2,center.x));
 const y=Math.max(height/2,center.y);
 return strokes.map(line=>line.map(p=>({x:x+(p.x-.5)*width,y:y+(p.y-.5)*height})));
}
function path(line:InkStroke,width:number,height:number){return line.map((p,i)=>(i?'L':'M')+(p.x*width).toFixed(2)+' '+(p.y*height).toFixed(2)).join(' ')+(line.length===1?' l.2 .2':'');}
function previewBox(mouse:InkPoint,ratio:number,requested:number,target?:Target|null){
 const width=Math.max(60,Math.min(requested,window.innerWidth-24,Math.max(60,window.innerHeight-130)*ratio)),height=width/ratio;
 if(target){
  const candidates=[{left:target.left+target.screenWidth+12,top:target.top},{left:target.left-width-12,top:target.top},{left:target.left,top:target.top-height-12},{left:target.left,top:target.top+target.screenHeight+12}];
  const fitting=candidates.find(p=>p.left>=12&&p.top>=88&&p.left+width<=window.innerWidth-12&&p.top+height<=window.innerHeight-12);
  if(fitting)return {width,height,...fitting};
 }
 return {width,height,left:Math.max(12,Math.min(window.innerWidth-width-12,mouse.x-width/2)),top:Math.max(88,Math.min(window.innerHeight-height-12,mouse.y-height/2))};
}

export function TouchpadInk({canvas,onCommit}:{canvas:RefObject<HTMLCanvasElement|null>;onCommit:(strokes:InkStroke[])=>void}){
 const [active,setActive]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [inkSource,setInkSource]=useState<'touchpad'|'phonepad'>('touchpad');
 const inkSourceRef=useRef<'touchpad'|'phonepad'>('touchpad');
 const [phoneSession,setPhoneSession]=useState<Session|null>(null),[phoneStatus,setPhoneStatus]=useState('等待手机连接');
 const [ratio,setRatio]=useState(1.65),[width,setWidth]=useState(140);
 const [previewSize,setPreviewSize]=useState(()=>{const saved=Number(localStorage.getItem('mathmaster-pad-preview-width'));return saved>=200&&saved<=1000?saved:420;});
 const [,resizeView]=useState(0);
 const [mouse,setMouse]=useState({x:window.innerWidth/2,y:window.innerHeight/2});
 const [target,setTarget]=useState<Target|null>(null);
 const [lines,setLines]=useState<InkStroke[]>([]),[ghost,setGhost]=useState<{lines:InkStroke[];left:number;top:number;width:number;height:number;dx:number;dy:number;scale:number}|null>(null);
 const pending=useRef<InkStroke[]>([]),stroke=useRef<InkStroke>([]),identity=useRef<number|null>(null);
 const targetRef=useRef<Target|null>(null),placement=useRef<Placement|null>(null);
 const hasMousePosition=useRef(false);
 const touching=useRef(false),ignoreUntilLift=useRef(false);
 const stream=useRef<EventSource|null>(null),token=useRef<string|null>(null),disposed=useRef(false),live=useRef(false);
 const commitHandler=useRef(onCommit);commitHandler.current=onCommit;
 const params=useRef({ratio,width,previewSize});params.current={ratio,width,previewSize};
 const mouseRef=useRef(mouse);mouseRef.current=mouse;
 const coverSequence=useRef(0);
 const lastTouch=useRef(0),ghostTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
 function targetAt(p:InkPoint):Target|null{
  const el=canvas.current;if(!el)return null;
  const rect=el.getBoundingClientRect(),paper=el.closest('.sketch-paper') as HTMLElement|null;
  if(rect.width<=0||rect.height<=0||!paper)return null;
  const clip=paper.getBoundingClientRect();
  const left=Math.max(0,rect.left,clip.left+paper.clientLeft),right=Math.min(window.innerWidth,rect.right,clip.left+paper.clientLeft+paper.clientWidth);
  const top=Math.max(0,rect.top,clip.top+paper.clientTop),bottom=Math.min(window.innerHeight,rect.bottom,clip.top+paper.clientTop+paper.clientHeight);
  if(p.x<left||p.x>=right||p.y<top||p.y>=bottom)return null;
  // Ignore our transparent overlay when hit testing, but reject controls and
  // calculators/windows covering the paper. Browser pointer moves never select.
  const stack=document.elementsFromPoint(p.x,p.y);
  if(stack.some(node=>node.closest('.touchpad-controls')))return null;
  const front=stack.find(node=>!node.closest('.touchpad-overlay,.touchpad-stamp'));
  if(front!==el)return null;
  const scale=rect.width/800,r=params.current.ratio;
  const w=Math.min(params.current.width,(right-left)/scale,(bottom-top)*r/scale),h=w/r;
  if(w<4||!Number.isFinite(w))return null;
  const cx=Math.max(left+w*scale/2,Math.min(right-w*scale/2,p.x));
  const cy=Math.max(top+h*scale/2,Math.min(bottom-h*scale/2,p.y));
  return {center:{x:(cx-rect.left)/scale,y:(cy-rect.top)/scale},width:w,ratio:r,left:cx-w*scale/2,top:cy-h*scale/2,screenWidth:w*scale,screenHeight:h*scale};
 }
 function phoneControl(patch:{selected?:boolean;reset?:boolean}){
  if(inkSourceRef.current==='phonepad'&&token.current)api('/api/phonepad/control',json({token:token.current,...patch})).catch(()=>{});
 }
 function selectTarget(p:InkPoint){const next=hasMousePosition.current?targetAt(p):null;if(!!next!==!!targetRef.current)phoneControl({selected:!!next});targetRef.current=next;setTarget(next);}
 function show(){setLines([...pending.current,...(stroke.current.length?[stroke.current]:[])]);}
 function lift(){if(stroke.current.length)pending.current.push(stroke.current);stroke.current=[];identity.current=null;show();}
 function commit(){
  lift();const destination=placement.current;
  if(!pending.current.length||!destination){pending.current=[];placement.current=null;return;}
  const placed=placeInk(pending.current,destination.center,destination.width,destination.ratio);
  phoneControl({reset:true});
  const rect=canvas.current?.getBoundingClientRect();
  if(rect&&inkSourceRef.current!=='phonepad'){
   const box=previewBox(mouseRef.current,destination.ratio,params.current.previewSize,targetRef.current),scale=rect.width/800;
   const corner=placeInk([[{x:0,y:0}]],destination.center,destination.width,destination.ratio)[0][0];
   setGhost({lines:pending.current,...box,dx:rect.left+corner.x*scale-box.left,dy:rect.top+corner.y*scale-box.top,scale:destination.width*scale/box.width});
   if(ghostTimer.current)clearTimeout(ghostTimer.current);ghostTimer.current=setTimeout(()=>setGhost(null),300);
  }
  pending.current=[];stroke.current=[];placement.current=null;setLines([]);commitHandler.current(placed);
 }
 function stop(save=true){
  if(save)commit();
  live.current=false;stream.current?.close();stream.current=null;
  if(token.current){const current=token.current;token.current=null;fetch('/api/'+inkSourceRef.current+'/stop',{...json({token:current}),headers:{'Content-Type':'application/json'},keepalive:true}).catch(()=>{});}
  setActive(false);
  targetRef.current=null;setTarget(null);placement.current=null;touching.current=false;ignoreUntilLift.current=false;hasMousePosition.current=false;
 }
 const stopRef=useRef(stop);stopRef.current=stop;
 const geometryRef=useRef(()=>{});geometryRef.current=()=>{if(live.current){commit();ignoreUntilLift.current=touching.current;selectTarget(mouseRef.current);}};
 const phoneMouseRef=useRef((event:PointerEvent)=>{});phoneMouseRef.current=event=>{
  if(!live.current||inkSourceRef.current!=='phonepad'||event.pointerType!=='mouse')return;
  commit();ignoreUntilLift.current=touching.current;
  const p={x:event.clientX,y:event.clientY};mouseRef.current=p;setMouse(p);hasMousePosition.current=true;selectTarget(p);
 };
 useEffect(()=>{const moved=(event:PointerEvent)=>phoneMouseRef.current(event);window.addEventListener('pointermove',moved);return()=>window.removeEventListener('pointermove',moved);},[]);
 useEffect(()=>{const resized=()=>resizeView(v=>v+1);window.addEventListener('resize',resized);return()=>window.removeEventListener('resize',resized);},[]);
 useEffect(()=>{if(!active)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{document.body.style.overflow=previous;};},[active]);
 useEffect(()=>{
  if(!active)return;
  const changed=()=>geometryRef.current();
  const observer=new ResizeObserver(changed);if(canvas.current)observer.observe(canvas.current);
  window.addEventListener('resize',changed);window.addEventListener('scroll',changed,true);
  return()=>{observer.disconnect();window.removeEventListener('resize',changed);window.removeEventListener('scroll',changed,true);};
 },[active]);
 useEffect(()=>{
  disposed.current=false;
  const leave=()=>stopRef.current();
  const cover=()=>{coverSequence.current++;leave();};
  const hide=()=>{if(document.hidden)leave();};
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'&&live.current){event.preventDefault();leave();}};
  window.addEventListener('mathmaster-cover',cover);window.addEventListener('blur',leave);window.addEventListener('pagehide',leave);
  document.addEventListener('visibilitychange',hide);window.addEventListener('keydown',key);
  return()=>{disposed.current=true;stopRef.current();if(ghostTimer.current)clearTimeout(ghostTimer.current);window.removeEventListener('mathmaster-cover',cover);window.removeEventListener('blur',leave);window.removeEventListener('pagehide',leave);document.removeEventListener('visibilitychange',hide);window.removeEventListener('keydown',key);};
 },[]);
 async function start(input:'touchpad'|'phonepad'='touchpad'){
  if(live.current)stop();
  inkSourceRef.current=input;setInkSource(input);
  setBusy(true);setError('');const startingCoverSequence=coverSequence.current;
  try{
   const session=await api<Session>('/api/'+input+'/start',json({}));token.current=session.token;
   if(input==='phonepad'){setPhoneSession(session);setPhoneStatus('等待手机连接');setWidth(800);params.current.width=800;}
   else {setWidth(140);params.current.width=140;}
   if(disposed.current||startingCoverSequence!==coverSequence.current||document.documentElement.dataset.covered==='true'){stop(false);return;}
   const device=session.devices[0],r=device.aspect_ratio??(device.x_range[1]-device.x_range[0])/(device.y_range[1]-device.y_range[0]);
   setRatio(r);params.current.ratio=r;
   // No guessed initial position: a real external mouse event must select paper.
   targetRef.current=null;setTarget(null);placement.current=null;touching.current=false;ignoreUntilLift.current=false;hasMousePosition.current=false;
   pending.current=[];stroke.current=[];identity.current=null;setLines([]);setActive(true);live.current=true;
   const source=new EventSource('/api/'+input+'/events?token='+encodeURIComponent(session.token));stream.current=source;
   source.onmessage=message=>{
    if(!live.current)return;
    let event:NativeEvent;try{event=JSON.parse(message.data);}catch{return;}
    if(event.type==='contact'){
     lastTouch.current=performance.now();
     touching.current=!!event.down;
     if(!event.down){lift();ignoreUntilLift.current=false;return;}
     if(ignoreUntilLift.current)return;
     if(!placement.current){const selected=targetRef.current;if(!selected){ignoreUntilLift.current=true;return;}placement.current={center:{...selected.center},width:selected.width,ratio:selected.ratio};}
     if(typeof event.x!=='number'||typeof event.y!=='number'||!Number.isFinite(event.x)||!Number.isFinite(event.y))return;
     if(identity.current!==null&&identity.current!==event.id)lift();
     identity.current=event.id??0;
     if(stroke.current.length>=10000||pending.current.length>=200){commit();return;}
     stroke.current.push({x:Math.max(0,Math.min(1,event.x)),y:Math.max(0,Math.min(1,event.y))});show();
    }else if(event.type==='surface'&&input==='phonepad'&&event.ratio){
     commit();setRatio(event.ratio);params.current.ratio=event.ratio;ignoreUntilLift.current=touching.current;selectTarget(mouseRef.current);
    }else if(event.type==='commit'&&input==='phonepad')commit();
    else if(event.type==='status'&&input==='phonepad')setPhoneStatus(event.message||'');
    else if(event.type==='mouse'){
     // Only a hardware mouse event commits. Browser pointermove from the pad is ignored.
     commit();
     ignoreUntilLift.current=touching.current;
     const x=(event.screen_x??window.screenX)-window.screenX;
     const y=(event.screen_y??window.screenY)-window.screenY-(window.outerHeight-window.innerHeight);
     mouseRef.current={x,y};setMouse({x,y});
     hasMousePosition.current=true;
     selectTarget({x,y});
    }else if(event.type==='pause')stopRef.current();
    else if(event.type==='error'){setError(event.message||'原始触控板连接已断开。');stopRef.current();}
   };
   source.onerror=()=>{if(live.current){setError(input==='phonepad'?'手机书写连接已断开，请重新开启。':'原始触控板连接已断开，请重新开启。');stopRef.current();}};
  }catch(e){setError((e as Error).message);stop(false);}
  finally{if(!disposed.current)setBusy(false);}
 }
 const {width:previewWidth,height:previewHeight,left,top}=inkSource==='phonepad'&&target
  ?{width:target.screenWidth,height:target.screenHeight,left:target.left,top:target.top}
  :previewBox(mouse,ratio,previewSize,target);
 return <>
  <button className="trackpad-toggle" aria-label="触控板书写" aria-pressed={active&&inkSource==='touchpad'} disabled={busy} title="读取触控板绝对坐标，移动外接鼠标收笔" onClick={()=>active&&inkSource==='touchpad'?stop():start()}>{busy?'连接中…':'触控板书写'}</button>
  <button className="trackpad-toggle" aria-label="手机书写" aria-pressed={active&&inkSource==='phonepad'} disabled={busy} title="手机整块区域对应电脑草稿落笔框" onClick={()=>active&&inkSource==='phonepad'?stop():start('phonepad')}>手机书写</button>
  {error&&<span className="touchpad-error" role="alert">{error}</span>}
  {active&&createPortal(<div className="touchpad-overlay" role="dialog" aria-label="触控板放大书写区">
   <div className="touchpad-controls" onPointerDownCapture={e=>{if(performance.now()-lastTouch.current<300)e.preventDefault();}}><span>{inkSource==='phonepad'?'手机书写 · Esc 收笔':'触控板 · Esc 收笔'}</span>{inkSource==='phonepad'&&phoneSession&&<span role="status">电脑 IP：{phoneSession.hosts?.join(' / ')||'请查看电脑网络设置'} · 端口 {phoneSession.port||8766} · 配对码 {phoneSession.code} · {phoneStatus}</span>}{inkSource==='touchpad'&&<label>书写区<input aria-label="书写区大小" type="range" min="200" max="1000" step="20" value={previewSize} onChange={e=>{const size=Number(e.target.value);setPreviewSize(size);localStorage.setItem('mathmaster-pad-preview-width',String(size));}}/><output>{Math.round(previewWidth)}px</output></label>}<label>落笔范围<select aria-label="落笔范围大小" style={inkSource==='phonepad'?{width:190}:undefined} value={width} onChange={e=>{commit();const next=Number(e.target.value);setWidth(next);params.current.width=next;selectTarget(mouseRef.current);}}><option value={80}>小</option><option value={140}>中</option><option value={220}>大</option><option value={400}>宽范围</option><option value={800}>草稿整宽（手机全区域）</option></select></label><button onClick={()=>{if(performance.now()-lastTouch.current>300)stop();}}>完成</button><span className="touchpad-location-status" role="status">{target?(inkSource==='phonepad'?'手机整块书写区 = 此落笔框 · 移动鼠标收笔并换位置':'在框内落笔 · 移动鼠标收笔并换位置'):'将外接鼠标移到草稿上，选择落笔位置'}</span></div>
   {target&&<div className="touchpad-target" role="img" aria-label="草稿落笔范围" style={{left:target.left,top:target.top,width:target.screenWidth,height:target.screenHeight}}><span>落笔范围</span></div>}
   {target&&<svg className="touchpad-writing" aria-label="放大笔迹" width={previewWidth} height={previewHeight} style={{left,top,...(inkSource==='phonepad'?{background:'transparent',boxShadow:'none',border:'none'}:{})}} viewBox={`0 0 ${previewWidth} ${previewHeight}`}>
    {inkSource==='touchpad'&&<path className="touchpad-center" d={`M${previewWidth/2-6} ${previewHeight/2}h12 M${previewWidth/2} ${previewHeight/2-6}v12`}/>}
    {lines.map((line,i)=><path key={i} d={path(line,previewWidth,previewHeight)} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>)}
   </svg>}
  </div>,document.body)}
  {ghost&&createPortal(<svg className="touchpad-stamp" style={{left:ghost.left,top:ghost.top,'--stamp-x':ghost.dx+'px','--stamp-y':ghost.dy+'px','--stamp-scale':ghost.scale} as CSSProperties} width={ghost.width} height={ghost.height} viewBox={`0 0 ${ghost.width} ${ghost.height}`}>{ghost.lines.map((line,i)=><path key={i} d={path(line,ghost.width,ghost.height)} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>)}</svg>,document.body)}
 </>;
}
