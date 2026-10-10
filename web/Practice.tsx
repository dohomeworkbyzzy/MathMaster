import { useCallback,useEffect,useRef,useState } from 'react';
import { ArrowLeft,ArrowRight, BookOpen, Check, CheckCircle2, Eraser, FileText, Maximize2, PencilLine, RotateCcw, Save, Send, X } from 'lucide-react';
import { api,json,type Attempt,type History,type Question,type Result } from './types';
import { Calculator } from './Calculator';
import { RichText } from './math';
import { ResultView } from './Steps';
import {TouchpadInk} from './TouchpadInk';

interface Point {x:number;y:number}
type Stroke=Point[];
function Sketch({value,onChange}:{value:string;onChange:(s:string)=>void}){
 const canvas=useRef<HTMLCanvasElement>(null);const drawing=useRef<Stroke>([]);
 const [penDown,setPenDown]=useState(false);
 const paper=useRef<HTMLDivElement>(null);const [paperSize,setPaperSize]=useState({width:800,height:450});
 let parsed:Stroke[]=[];try{const obj=JSON.parse(value||'[]');if(Array.isArray(obj))parsed=obj;}catch{}
 const strokes=useRef(parsed);strokes.current=parsed;
 let logicalHeight=450;for(const stroke of parsed)for(const point of stroke)logicalHeight=Math.max(logicalHeight,point.y+12);
 const canvasHeight=Math.ceil(Math.max(logicalHeight,paperSize.height*800/Math.max(1,paperSize.width)));
 function draw(extra:Stroke=[]){const el=canvas.current;const ctx=el?.getContext('2d');if(!el||!ctx)return;ctx.clearRect(0,0,800,el.height);ctx.strokeStyle='#333';ctx.lineWidth=2;ctx.lineCap='round';ctx.lineJoin='round';for(const line of [...strokes.current,extra]){if(line.length===0)continue;ctx.beginPath();ctx.moveTo(line[0].x,line[0].y);if(line.length===1)ctx.lineTo(line[0].x+0.2,line[0].y+0.2);for(const p of line.slice(1))ctx.lineTo(p.x,p.y);ctx.stroke();}}
 useEffect(()=>{const element=paper.current;if(!element)return;const observer=new ResizeObserver(()=>setPaperSize({width:element.clientWidth,height:element.clientHeight}));observer.observe(element);return()=>observer.disconnect();},[]);
 useEffect(()=>{draw();},[value,canvasHeight]);
 function point(e:React.PointerEvent<HTMLCanvasElement>){const r=e.currentTarget.getBoundingClientRect();return {x:(e.clientX-r.left)*800/r.width,y:(e.clientY-r.top)*e.currentTarget.height/r.height};}
 function finish(){
  setPenDown(false);
  if(drawing.current.length){const next=[...strokes.current,drawing.current];drawing.current=[];strokes.current=next;onChange(JSON.stringify(next));}
 }
 const finishRef=useRef(finish);finishRef.current=finish;
 useEffect(()=>{
  const blur=()=>finishRef.current(),hide=()=>{if(document.hidden)finishRef.current();};
  window.addEventListener('blur',blur);document.addEventListener('visibilitychange',hide);
  return()=>{window.removeEventListener('blur',blur);document.removeEventListener('visibilitychange',hide);};
 },[]);
 function start(e:React.PointerEvent<HTMLCanvasElement>){
  if(e.button!==0||!e.isPrimary)return;
  e.preventDefault();e.currentTarget.focus({preventScroll:true});
  e.currentTarget.setPointerCapture(e.pointerId);
  drawing.current=[point(e)];setPenDown(true);draw(drawing.current);
 }
 function move(e:React.PointerEvent<HTMLCanvasElement>){
  if(!e.isPrimary||!drawing.current.length)return;
  if(drawing.current.length>=10000){finish();return;}
  drawing.current.push(point(e));draw(drawing.current);
 }
 return <div className="sketch"><div className="section-heading"><span><PencilLine size={14}/> 电子草稿</span><div className="toolbar"><TouchpadInk canvas={canvas} onCommit={lines=>{finish();const next=[...strokes.current,...lines];strokes.current=next;onChange(JSON.stringify(next));}}/>{penDown&&<span className="pen-status" role="status">落笔中</span>}<button title="撤销笔画" onClick={()=>onChange(JSON.stringify(strokes.current.slice(0,-1)))}><RotateCcw size={14}/></button><button title="清空草稿" onClick={()=>onChange('[]')}><Eraser size={14}/></button></div></div><div className="sketch-paper" ref={paper}><canvas aria-label="电子草稿画布" tabIndex={0} width="800" height={canvasHeight} ref={canvas} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish} onBlur={finish} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();finish();}}}/></div></div>;
}

const tabId=sessionStorage.getItem('mathmaster-tab-id')||crypto.randomUUID();
sessionStorage.setItem('mathmaster-tab-id',tabId);

function questionVersion(q:Question){return q.attempt?.updated_at||null;}

function useAttempt(q:Question,notify:(s:string)=>void){
 const base:Attempt={answer:q.attempt?.answer||'',notes:q.attempt?.notes||'',draft:q.attempt?.draft||'',status:q.attempt?.status||'未作答',wrong:!!q.attempt?.wrong};
 const key='mathmaster-unsaved-'+q.id+'-'+tabId;let initial=base;let recovered:Attempt|null=null;
 try{const backup=localStorage.getItem(key);if(backup){const savedBackup=JSON.parse(backup);if(savedBackup.baseVersion===questionVersion(q))initial=savedBackup.attempt;else recovered=savedBackup.attempt;}}catch{}
 const [recovery,setRecovery]=useState<Attempt|null>(recovered);
 const version=useRef(questionVersion(q));
 const [attempt,setState]=useState(initial);const latest=useRef(attempt);latest.current=attempt;const saved=useRef(JSON.stringify(base));const chain=useRef(Promise.resolve());const timer=useRef<ReturnType<typeof setTimeout>|null>(null);const mounted=useRef(true);
 const [saveState,setSaveState]=useState('已保存');
 const flush=useCallback(async()=>{
  if(timer.current)clearTimeout(timer.current);
  const snapshot=latest.current, encoded=JSON.stringify(snapshot);
  if(encoded===saved.current){await chain.current;return;}
  chain.current=chain.current.catch(()=>{}).then(async()=>{
   if(encoded===saved.current)return;
   if(mounted.current)setSaveState('保存中…');
   try {const stored=await api<{updated_at:string}>('/api/questions/'+q.id+'/attempt',json({...snapshot,expected_updated_at:version.current},'PUT'));version.current=stored.updated_at;saved.current=encoded;
    if(JSON.stringify(latest.current)===encoded)localStorage.removeItem(key);
    else localStorage.setItem(key,JSON.stringify({attempt:latest.current,baseVersion:version.current}));
    if(mounted.current)setSaveState(JSON.stringify(latest.current)===encoded?'已保存':'待保存');
   }catch(e){if(mounted.current)setSaveState('本机草稿保留 · 数据库保存失败');throw e;}
  });
  await chain.current;
 },[q.id]);
 useEffect(()=>{timer.current=setTimeout(()=>{flush().catch(e=>notify((e as Error).message));},700);return()=>{if(timer.current)clearTimeout(timer.current);};},[attempt,flush]);
 useEffect(()=>()=>{mounted.current=false;flush().catch(()=>{});},[flush]);
 function update(patch:Partial<Attempt>){setState(prev=>{const next={...prev,...patch};latest.current=next;try{localStorage.setItem(key,JSON.stringify({attempt:next,baseVersion:version.current}));}catch{notify('浏览器草稿缓存已满，请及时保存并备份。');}return next;});setSaveState('待保存');}
 function restoreRecovery(){if(recovery){update(recovery);setRecovery(null);}}
 function downloadRecovery(){if(!recovery)return;const url=URL.createObjectURL(new Blob([JSON.stringify(recovery,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='MathMaster-未同步草稿.json';a.click();URL.revokeObjectURL(url);}
 return {attempt,update,flush,saveState,recovery,restoreRecovery,downloadRecovery};
}

export function Practice({question,onBack,onNext,onEdit,notify,registerFlush}:{question:Question;onBack:()=>void;onNext:(n:number)=>void;onEdit:()=>void;notify:(s:string)=>void;registerFlush:(fn:(()=>Promise<void>)|null)=>void}){
 const {attempt,update,flush,saveState,recovery,restoreRecovery,downloadRecovery}=useAttempt(question,notify);const [notePreview,setNotePreview]=useState(false);const [reference,setReference]=useState(false);
 const [collapsed,setCollapsed]=useState(false);const [floating,setFloating]=useState(false);const [fullscreen,setFullscreen]=useState(false);const [send,setSend]=useState('');const [selection,setSelection]=useState<string|null>(null);const [calculations,setCalculations]=useState(question.calculations||[]);
 const [autoLayout,setAutoLayout]=useState(true);const [questionHeight,setQuestionHeight]=useState(240);
 const [manualAreaHeight,setManualAreaHeight]=useState(0);
 const [availableHeight,setAvailableHeight]=useState(650);const [calculatorWidth,setCalculatorWidth]=useState(340);
 const panes=useRef<HTMLDivElement>(null);const questionContent=useRef<HTMLDivElement>(null);
 const [floatPos,setFloatPos]=useState({x:Math.max(20,window.innerWidth-530),y:110});
 const minimumDraft=210;
 useEffect(()=>{
  const area=panes.current,content=questionContent.current;if(!area||!content)return;
  const measure=()=>{
   const available=Math.max(410,window.innerHeight-area.getBoundingClientRect().top-window.scrollY-12);
   setAvailableHeight(available);
   if(autoLayout)setQuestionHeight(Math.max(140,Math.ceil(content.getBoundingClientRect().height)+2));
   else setQuestionHeight(height=>Math.max(140,Math.min(height,Math.max(available,manualAreaHeight)-minimumDraft-10)));
  };
  const observer=new ResizeObserver(measure);observer.observe(content);observer.observe(area);
  window.addEventListener('resize',measure);measure();
  return()=>{observer.disconnect();window.removeEventListener('resize',measure);};
 },[autoLayout,manualAreaHeight]);
 useEffect(()=>{registerFlush(flush);return()=>registerFlush(null);},[flush]);
 function resizeQuestion(e:React.PointerEvent<HTMLDivElement>){
  e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);setAutoLayout(false);
  const start=e.clientY,initial=questionHeight,areaHeight=Math.max(availableHeight,questionHeight+minimumDraft+10);
  setManualAreaHeight(areaHeight);
  const element=e.currentTarget;
  const move=(event:PointerEvent)=>setQuestionHeight(Math.max(140,Math.min(areaHeight-minimumDraft-10,initial+event.clientY-start)));
  const end=()=>{element.removeEventListener('pointermove',move);element.removeEventListener('pointerup',end);element.removeEventListener('pointercancel',end);};
  element.addEventListener('pointermove',move);element.addEventListener('pointerup',end);element.addEventListener('pointercancel',end);
 }
 function resizeCalculator(e:React.PointerEvent<HTMLDivElement>){
  e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);
  const start=e.clientX,initial=calculatorWidth,element=e.currentTarget;
  const move=(event:PointerEvent)=>setCalculatorWidth(Math.max(280,Math.min((panes.current?.clientWidth||1000)*.5,initial+start-event.clientX)));
  const end=()=>{element.removeEventListener('pointermove',move);element.removeEventListener('pointerup',end);element.removeEventListener('pointercancel',end);};
  element.addEventListener('pointermove',move);element.addEventListener('pointerup',end);element.addEventListener('pointercancel',end);
 }
 function dragFloat(e:React.PointerEvent){if((e.target as HTMLElement).closest('button'))return;const sx=e.clientX,sy=e.clientY,start={...floatPos};const move=(ev:PointerEvent)=>setFloatPos({x:Math.min(window.innerWidth-200,Math.max(0,start.x+ev.clientX-sx)),y:Math.min(window.innerHeight-60,Math.max(0,start.y+ev.clientY-sy))});const end=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end);};window.addEventListener('pointermove',move);window.addEventListener('pointerup',end);}
 async function insert(result:Result){try{await api('/api/questions/'+question.id+'/calculations/'+result.history_id,json({}));const h=await api<Question>('/api/questions/'+question.id);setCalculations(h.calculations||[]);notify('已将结果和完整步骤插入本题笔记');}catch(e){notify((e as Error).message);}}
 function exportNotes(){function lines(steps:Result['steps']):string{return steps.map(st=>`${st.explanation_zh}\n\n$$${st.before_latex}$$\n\n$$${st.after_latex}$$\n\n${lines(st.children)}`).join('\n');}const content=`# 第 ${question.number} 题\n\n${question.text}\n\n## 我的答案\n\n${attempt.answer}\n\n## 解题笔记\n\n${attempt.notes}\n\n`+calculations.map(h=>`## ${h.result.method}\n\n$$${h.result.input_latex}$$\n\n$$${h.result.result_latex}$$\n\n${lines(h.result.steps)}\n条件：${h.result.assumptions.join('；')}\n提示：${h.result.warnings.join('；')}`).join('\n');const url=URL.createObjectURL(new Blob([content],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='MathMaster-解题笔记.md';a.click();URL.revokeObjectURL(url);}
 return <><div className="practice-bar"><button className="text-button" onClick={onBack}><ArrowLeft size={15}/>返回题库</button><div className="practice-title"><span className="subject-tag">{question.subject}</span><b>第 {question.number} 题</b><span>{question.paper_title||'本地题库'}</span></div><div className="practice-tools"><span className="save-status"><Save size={13}/>{saveState}</span><button className="secondary small" aria-pressed={autoLayout} onClick={()=>{setManualAreaHeight(Math.max(availableHeight,questionHeight+minimumDraft+10));setAutoLayout(value=>!value);}}>{autoLayout?'自动调节：开':'自动调节：关'}</button><button className="secondary small" onClick={()=>onNext(-1)}>上一题</button><button className="secondary small" onClick={()=>onNext(1)}>下一题</button>{collapsed&&<button className="secondary small" onClick={()=>setCollapsed(false)}>展开计算器</button>}</div></div>
 <div className="practice-panes" ref={panes} style={{height:autoLayout?Math.max(availableHeight,questionHeight+minimumDraft+10):Math.max(availableHeight,manualAreaHeight)}}>
 <div className="practice-stack">
  <section className="question-pane pane" aria-label="题目区" style={{height:questionHeight}}>
   <div className="question-content" ref={questionContent}>
    <div className="pane-heading"><span>题目{!question.confirmed&&<small className="question-review">题图 / 文字待核对</small>}</span><div><button className="text-button" onClick={()=>setSelection(window.getSelection()?.toString().trim()||'')}><Send size={13}/>选中表达式发送到计算器</button><button className="text-button" onClick={onEdit}>{question.confirmed?'编辑题目':'检查拆题'}</button></div></div>
    {question.images.length>0?<details className="question-context"><summary>题目说明与识别文字</summary><div className="question-text" onMouseUp={()=>{const text=window.getSelection()?.toString().trim();if(text&&text.length<=600)setSelection(text);}}><RichText text={question.text||'请以原始题图为准。'}/></div>{question.source_filename&&<a className="text-button" href={'/api/files/'+question.source_filename} target="_blank" rel="noreferrer">打开原始试卷 ↗</a>}</details>:<div className="question-text" onMouseUp={()=>{const text=window.getSelection()?.toString().trim();if(text&&text.length<=600)setSelection(text);}}><RichText text={question.text}/></div>}
    <div className="question-images">{question.images.map((src,i)=><a href={'/api/files/'+src} target="_blank" key={src} rel="noreferrer"><img className="question-image" src={'/api/files/'+src} alt={`题目原始截图 ${i+1}`}/></a>)}</div>
   </div>
  </section>
  <div className="question-draft-divider" role="separator" aria-label="调整题目与草稿高度" aria-orientation="horizontal" aria-valuemin={140} aria-valuemax={Math.max(availableHeight,questionHeight+minimumDraft+10)-minimumDraft-10} aria-valuenow={questionHeight} tabIndex={0} onPointerDown={resizeQuestion} onDoubleClick={()=>setAutoLayout(true)} onKeyDown={e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();setAutoLayout(false);setManualAreaHeight(Math.max(availableHeight,questionHeight+minimumDraft+10));setQuestionHeight(height=>Math.max(140,Math.min(Math.max(availableHeight,manualAreaHeight,questionHeight+minimumDraft+10)-minimumDraft-10,height+(e.key==='ArrowUp'?-24:24))));}if(e.key==='Home'){e.preventDefault();setAutoLayout(true);}}}><span/></div>
  <section className="notes-pane pane" aria-label="草稿区">
   <div className="pane-heading"><span>草稿与笔记</span><div><button className="text-button" onClick={()=>setNotePreview(v=>!v)}>{notePreview?'编辑笔记':'预览笔记'}</button><button className="text-button" onClick={exportNotes}>导出</button></div></div>
   {recovery&&<div className="warnings"><p>发现未同步草稿，但数据库已有新版本。已保留当前记录，未自动覆盖。</p><p>旧笔记：{recovery.notes.slice(0,160)||'（空）'}</p><button className="text-button" onClick={downloadRecovery}>下载未同步草稿</button><button className="text-button" onClick={restoreRecovery}>将旧草稿加载到编辑器</button></div>}
   <div className="draft-body"><Sketch value={attempt.draft} onChange={draft=>update({draft})}/><div className="draft-tools"><label className="field-label">解题笔记</label>{notePreview?<RichText text={attempt.notes||'还没有笔记。'}/>:<textarea className="notes-editor" aria-label="解题笔记" placeholder="记录解题思路，支持 $LaTeX$" value={attempt.notes} onChange={e=>update({notes:e.target.value})}/>}
    <div className="question-answer"><label className="field-label">我的答案<textarea value={attempt.answer} aria-label="我的答案" placeholder="最终答案" onChange={e=>update({answer:e.target.value,status:'作答中'})}/></label><div className="answer-tools"><button className={'secondary small '+(attempt.wrong?'wrong-selected':'')} onClick={()=>update({wrong:!attempt.wrong})}>{attempt.wrong?'已加入错题本':'加入错题本'}</button><button className={'primary small '+(attempt.status==='已完成'?'completed':'')} onClick={()=>update({status:attempt.status==='已完成'?'作答中':'已完成'})}><CheckCircle2 size={14}/>{attempt.status==='已完成'?'已完成':'完成本题'}</button></div><button className="text-button" onClick={()=>setReference(value=>!value)}>{reference?'收起':'查看'}参考答案</button>{reference&&<RichText text={question.reference_answer||'本题尚未录入参考答案，可在编辑题目中添加。'}/>}</div>
    {calculations.length>0&&<div className="note-calculations"><div className="section-heading"><b>已插入的计算推导</b><small>{calculations.length} 条</small></div>{calculations.map(h=><ResultView result={h.result} key={h.id} notify={notify}/>)}</div>}
   </div></div>
  </section>
 </div>
 {!collapsed&&!floating&&!fullscreen&&<div className="pane-divider" role="separator" aria-label="调整计算器宽度" onPointerDown={resizeCalculator}/>}
 <div className={(fullscreen?'fullscreen-calc':floating?'floating-calc':'calculator-pane')+(collapsed?' hidden':'')} style={floating&&!fullscreen?{left:floatPos.x,top:floatPos.y}:!fullscreen?{flexBasis:calculatorWidth}:{}}>{(floating||fullscreen)&&<div className="float-handle" onPointerDown={dragFloat}><span>{fullscreen?'全屏计算工作台':'拖动标题可移动计算器'}</span><button className="text-button" onClick={()=>{setFloating(false);setFullscreen(false);}}>返回工作台 <X size={15}/></button></div>}<Calculator questionId={question.id} compact={!fullscreen} send={send} notify={notify} onInsert={insert} onCollapse={()=>setCollapsed(true)} onFloat={()=>{setFloating(value=>!value);setFullscreen(false);}} onFullscreen={()=>setFullscreen(value=>!value)}/></div>
 </div>
 {selection!==null&&<div className="modal-backdrop"><div className="modal"><div className="modal-heading"><h3>确认数学表达式</h3><button className="icon-button" onClick={()=>setSelection(null)}><X size={18}/></button></div><p className="muted">题目文字或 OCR 可能识别错误。请确认表达式完整、公式准确，再发送到计算器。</p><textarea aria-label="确认数学表达式" value={selection} onChange={e=>setSelection(e.target.value)} placeholder="例如 2x/(x^2+1)"/><div className="modal-actions"><button className="secondary" onClick={()=>setSelection(null)}>取消</button><button className="primary" disabled={!selection.trim()} onClick={()=>{setSend(selection);setCollapsed(false);setSelection(null);}}>确认并填入计算器 <ArrowRight size={15}/></button></div></div></div>}
 </>;
}
