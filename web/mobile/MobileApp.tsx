import {ToolVerification} from '../ToolVerification';
import {DifficultyPanel} from '../DifficultyPanel';
import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,BookOpen,Check,History,Search,Settings2,Sparkles} from 'lucide-react';
import {api,json,type Question,type Paper,type RecentQuestion,userStorageKey} from '../types';
import {APISettings} from '../APISettings';
import {UserMenu} from '../UserMenu';
import {RichText,Formula} from '../math';
import {useTutorSession} from '../useTutorSession';
import './mobile.css';

type Photo={id:string;url:string};
type RecordItem={id:string;answer:string;reasoning:string;created_at:string;images:Photo[]};
type Session={id:string;version:number;busy:boolean;stale:boolean;turns:{id:string;user_text:string;message:string;status:string;error:string}[];state:{current_latex:string;next_question:string;cards:{number:number;label:string;result:Record<string,unknown>&{result_latex?:string}}[]}};
function message(e:unknown){return e instanceof Error?e.message:String(e);}
function cached<T>(key:string,fallback:T):T{try{return JSON.parse(localStorage.getItem(key)||'null')??fallback;}catch{return fallback;}}

export default function MobileApp(){
 const [view,setView]=useState('library'),[q,setQ]=useState<Question|null>(null),[toast,setToast]=useState(''),[error,setError]=useState('');
 const [items,setItems]=useState<Question[]>([]),[papers,setPapers]=useState<Paper[]>([]),[recent,setRecent]=useState<RecentQuestion[]>([]);
 const [search,setSearch]=useState(''),[subject,setSubject]=useState(''),[paper,setPaper]=useState(''),[more,setMore]=useState(false),[busy,setBusy]=useState(false),[opening,setOpening]=useState(false);
 const flush=useRef<(()=>Promise<void>)|null>(null),sequence=useRef(0),timer=useRef<ReturnType<typeof setTimeout>|null>(null);
 function notify(s:string){setToast(s);if(timer.current)clearTimeout(timer.current);timer.current=setTimeout(()=>setToast(''),8000);}
 async function load(append=false){const epoch=++sequence.current;setBusy(true);setError('');try{
  const query=new URLSearchParams({search,subject,paper_id:paper,limit:'30',offset:String(append?items.length:0)});
  const rows=await api<Question[]>('/api/questions?'+query);if(sequence.current!==epoch)return;setItems(old=>append?[...old,...rows]:rows);setMore(rows.length===30);
 }catch(e){if(sequence.current===epoch)setError(message(e));}finally{if(sequence.current===epoch)setBusy(false);}}
 useEffect(()=>{window.scrollTo(0,0);},[view,q?.id]);
 useEffect(()=>{if(view==='library'&&!q){const t=setTimeout(()=>void load(),250);return()=>clearTimeout(t);}},[search,subject,paper,view,q?.id]);
 useEffect(()=>{void api<Paper[]>('/api/papers').then(setPapers).catch(e=>setError(message(e)));},[]);
 useEffect(()=>{if(view==='records'&&!q)void api<RecentQuestion[]>('/api/practice/recent?limit=20').then(setRecent).catch(e=>setError(message(e)));},[view,q?.id]);
 async function navigate(next:string){try{await flush.current?.();setQ(null);setError('');setView(next);}catch(e){notify(message(e));}}
 async function open(id:string){if(opening)return;setOpening(true);try{await flush.current?.();const next=await api<Question>('/api/questions/'+id);await api('/api/practice/'+id+'/visit',json({}));setQ(next);setError('');}catch(e){notify(message(e));}finally{setOpening(false);}}
 return <div className="mobile-app"><header className="m-header"><div className="m-brand"><span>M∫</span><div><b>MathMaster</b><small>随时看题 · 纸上练习</small></div></div><UserMenu beforeChange={async()=>{await flush.current?.();}}/><button className="m-icon" aria-label="连接设置" onClick={()=>void navigate('settings')}><Settings2 size={21}/></button></header>
 <main className="m-main">{q?<MobileQuestion key={q.id} question={q} notify={notify} onBack={()=>void navigate(view)} onOpen={id=>void open(id)} flush={flush}/>:<>
 {view==='library'&&<><div className="m-heading"><small>YOUR PRACTICE SPACE</small><h1>今天，练哪一题？</h1><p>在纸上写下思路，把进步留在这里。</p></div><div className="m-search"><Search size={18}/><input aria-label="搜索题库" placeholder="搜索题目或知识点" value={search} onChange={e=>setSearch(e.target.value)}/></div><div className="m-filters"><select aria-label="科目" value={subject} onChange={e=>{setSubject(e.target.value);setPaper('');}}><option value="">全部科目</option>{['数学一','数学二','数学三','408'].map(s=><option key={s}>{s}</option>)}</select><select aria-label="试卷" value={paper} onChange={e=>setPaper(e.target.value)}><option value="">全部试卷</option>{papers.filter(p=>!subject||p.subject===subject).map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></div>
 {error&&<div role="alert" className="m-error">{error}<button onClick={()=>void load()}>重新连接</button></div>}
 <div className="m-list">{items.map(item=><button disabled={opening} className="m-question-card" key={item.id} onClick={()=>void open(item.id)}><div><span className="m-tag">{item.subject}</span><small>{item.status==='已完成'?'已完成':item.wrong?'待复习':'待练习'}</small></div><h3>{item.paper_title||'独立题目'} · 第 {item.number} 题</h3><p>{item.text.slice(0,160)||'查看原始题图'}</p><span className="m-card-action">开始练习 →</span></button>)}</div>{busy&&<p role="status">正在读取题库…</p>}{!busy&&!error&&items.length===0&&<div className="m-empty"><BookOpen/><h3>这里还没有题目</h3><p>可更换筛选条件，或在电脑网站导入试卷。</p></div>}{more&&<button className="secondary wide" disabled={busy} onClick={()=>void load(true)}>加载更多</button>}</>}
 {view==='records'&&<><div className="m-heading"><small>KEEP GOING</small><h1>我的练习记录</h1><p>打开题目，查看已上传的答案和照片。</p></div>{recent.map(r=><button className="m-question-card" key={r.id} disabled={opening} onClick={()=>void open(r.id)}><span className="m-tag">{r.status||'浏览过'}</span><h3>{r.paper_title||r.subject} · 第 {r.number} 题</h3><p>{r.text.slice(0,100)}</p><small>{new Date(r.last_practiced_at).toLocaleString('zh-CN')}</small></button>)}{!recent.length&&<p className="m-empty">暂无最近练习记录，先选一道题开始吧。</p>}{error&&<p role="alert" className="m-error">{error}</p>}</>}
 {view==='settings'&&<><div className="m-heading"><small>MAKE IT YOURS</small><h1>设置</h1></div><section className="m-panel"><h2>网站服务器</h2><p className="m-wrap">当前连接：{location.origin}</p>{navigator.userAgent.includes('MathMasterMobile/')?<a className="secondary wide m-server-settings" href="mathmaster://settings/servers">管理服务器地址</a>:<p>在安卓 App 的此设置页可添加、编辑和切换多套 IP＋端口或域名。浏览器中可通过地址栏更换网站。</p>}<p>题库和记录属于当前连接的服务器，切换地址前请先同步做题记录。</p><p>手机连接本机电脑时，请填写电脑的局域网 IP，而非 127.0.0.1；网站后端需在线并允许该地址访问。</p></section><APISettings notify={notify}/></>}
 </>}</main><nav className="m-nav" aria-label="手机导航">{[['library',BookOpen,'题库'],['records',History,'记录'],['settings',Settings2,'设置']].map(([id,Icon,label])=>{const I=Icon as typeof BookOpen;return <button key={id as string} className={view===id?'active':''} onClick={()=>void navigate(id as string)}><I size={20}/><span>{label as string}</span></button>;})}</nav>{toast&&<div role="status" className="m-toast" onClick={()=>setToast('')}>{toast}</div>}</div>;
}

function MobileQuestion({question:q,notify,onBack,onOpen,flush}:{question:Question;notify:(s:string)=>void;onBack:()=>void;onOpen:(id:string)=>void;flush:React.MutableRefObject<(()=>Promise<void>)|null>}){
 const key=userStorageKey('mathmaster-mobile-answer-'+q.id);
 type Draft={answer:string;notes:string;status:string;wrong:boolean;expected_updated_at:string|null;dirty:boolean};
 const initial:Draft={answer:q.attempt?.answer||'',notes:q.attempt?.notes||'',status:q.attempt?.status||'作答中',wrong:!!q.attempt?.wrong,expected_updated_at:q.attempt?.updated_at||null,dirty:false};
 const [draft,setDraft]=useState<Draft>(()=>{const local=cached(key,initial);return local.dirty?local:initial;}),[tab,setTab]=useState('answer'),[photos,setPhotos]=useState<Photo[]>([]),[photosLoaded,setPhotosLoaded]=useState(false),[records,setRecords]=useState<RecordItem[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[image,setImage]=useState(''),[backup,setBackup]=useState<Draft|null>(()=>cached(key+'-conflict',null));
 const current=useRef(draft),saving=useRef<Promise<void>|null>(null),version=useRef(0),photoBusy=useRef(false),photosReady=useRef(false),desktopDraft=useRef(q.attempt?.draft||'');
 current.current=draft;
 useEffect(()=>{localStorage.setItem(key,JSON.stringify(draft));},[draft]);
 function change(next:Partial<Draft>){setDraft(d=>({...d,...next,dirty:true}));}
 async function history(){const r=await api<{history:RecordItem[]}>('/api/grading/questions/'+q.id);setRecords(r.history);}
 useEffect(()=>{void Promise.all([api<{version:number;images:Photo[]}>('/api/grading/questions/'+q.id+'/draft').then(r=>{version.current=r.version;setPhotos(r.images);photosReady.current=true;setPhotosLoaded(true);}),history()]).catch(e=>setError(message(e)));},[]);
 async function saveAttempt(){
  if(photoBusy.current)throw new Error('作答图片正在上传，请稍候。');
  if(saving.current)return saving.current;
  if(!current.current.dirty)return;
  const snapshot=current.current;
  const task=(async()=>{const r=await api<{updated_at:string}>('/api/questions/'+q.id+'/attempt',json({...snapshot,dirty:undefined,draft:desktopDraft.current},'PUT'));
   const latest=current.current;const next={...latest,expected_updated_at:r.updated_at,dirty:latest!==snapshot};current.current=next;localStorage.setItem(key,JSON.stringify(next));setDraft(next);
  })();saving.current=task;try{await task;}finally{saving.current=null;}
 }
 useEffect(()=>{flush.current=saveAttempt;return()=>{flush.current=null;};},[]);
 useEffect(()=>{const handler=(e:BeforeUnloadEvent)=>{if(current.current.dirty||photoBusy.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[]);
 async function persistPhotos(next:Photo[]){const r=await api<{version:number;images:Photo[]}>('/api/grading/questions/'+q.id+'/draft',json({images:next.map(p=>p.id),version:version.current},'PUT'));version.current=r.version;setPhotos(r.images);}
 async function upload(files:FileList|null){if(!files?.length||photoBusy.current)return;if(!photosReady.current){setError('图片记录尚未读取完成，请重新打开题目后再上传。');return;}if(files.length+photos.length>5){setError('每题最多上传 5 张作答照片。');return;}
  photoBusy.current=true;setBusy(true);setError('');let next=[...photos];try{for(const file of Array.from(files)){if(file.size>10*1024*1024)throw new Error('每张照片最多 10 MB。');const body=new FormData();body.append('file',file);const p=await api<Photo>('/api/grading/questions/'+q.id+'/images',{method:'POST',body});next=[...next,p];await persistPhotos(next);}notify('照片已上传到当前网站');}catch(e){setError(message(e));}finally{photoBusy.current=false;setBusy(false);}}
 async function submit(){if(busy)return;setBusy(true);setError('');try{await saveAttempt();await api('/api/grading/questions/'+q.id+'/record',json({answer:current.current.answer,reasoning:current.current.notes,images:photos.map(p=>p.id)}));await history();notify('做题记录已上传');}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <><button className="m-back" onClick={onBack}><ArrowLeft size={17}/>返回{q.subject}题库</button><section className="m-panel m-problem"><span className="m-tag">{q.subject}</span><h1>{q.paper_title||'独立练习'} · 第 {q.number} 题</h1><RichText text={q.text}/>{q.images.map((src,i)=><button className="m-image-button" key={src} onClick={()=>setImage('/api/files/'+src)}><img src={'/api/files/'+src} alt={'题目原图 '+(i+1)}/></button>)}{!q.confirmed&&<p className="muted">题干尚未校对，请以原图为准。</p>}</section>
 <div className="m-tabs"><button className={tab==='answer'?'active':''} onClick={()=>setTab('answer')}>作答与上传</button><button className={tab==='ai'?'active':''} onClick={()=>{void saveAttempt().then(()=>setTab('ai')).catch(e=>setError(message(e)));}}><Sparkles size={16}/>AI 解题 / 推荐</button></div>
 <div hidden={tab!=='answer'}><section className="m-panel"><h2>把纸上的思路留在这里</h2><label>我的答案<textarea aria-label="我的答案" maxLength={20000} value={draft.answer} onChange={e=>change({answer:e.target.value})} placeholder="选项、结果或解题过程…"/></label><label>做题笔记<textarea aria-label="做题笔记" maxLength={30000} value={draft.notes} onChange={e=>change({notes:e.target.value})} placeholder="卡在哪里？下次要注意什么？"/></label><div className="m-filters"><label>进度<select aria-label="作答进度" value={draft.status} onChange={e=>change({status:e.target.value})}><option>未作答</option><option>作答中</option><option>已完成</option></select></label><label className="m-check"><input type="checkbox" checked={draft.wrong} onChange={e=>change({wrong:e.target.checked})}/>加入错题本</label></div>
 <label className="m-upload">＋ 上传纸上作答照片<input aria-label="上传作答照片" type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={busy||!photosLoaded} onChange={e=>{void upload(e.target.files);e.target.value='';}}/></label><small>每题最多 5 张，每张 10 MB；支持 PNG、JPEG、WebP。</small><div className="m-photos">{photos.map((p,i)=><div key={p.id}><button className="m-image-button" onClick={()=>setImage(p.url)}><img src={p.url} alt={'作答照片 '+(i+1)}/></button><button disabled={busy} onClick={async()=>{setBusy(true);photoBusy.current=true;try{await persistPhotos(photos.filter(item=>item.id!==p.id));}catch(e){setError(message(e));}finally{photoBusy.current=false;setBusy(false);}}}>移除第 {i+1} 张</button></div>)}</div>
 {error&&<p role="alert" className="m-error">{error}</p>}{error.includes('其他窗口更新')&&<button className="secondary wide" onClick={async()=>{try{const fresh=await api<Question>('/api/questions/'+q.id);const old=current.current;localStorage.setItem(key+'-conflict',JSON.stringify(old));setBackup(old);desktopDraft.current=fresh.attempt?.draft||'';setDraft({answer:fresh.attempt?.answer||'',notes:fresh.attempt?.notes||'',status:fresh.attempt?.status||'作答中',wrong:!!fresh.attempt?.wrong,expected_updated_at:fresh.attempt?.updated_at||null,dirty:false});setError('');notify('已读取网站最新记录，手机未同步文字保存在下方副本中');}catch(e){setError(message(e));}}}>保留手机副本，读取网站最新记录</button>}{backup&&<details><summary>冲突前的手机文字副本（可复制合并）</summary><p className="m-wrap">{backup.answer}</p><p className="m-wrap">{backup.notes}</p><button className="secondary" onClick={()=>{change({answer:backup.answer,notes:backup.notes});notify('手机文字已填回，请核对后上传');}}>用此副本填回答案和笔记</button></details>}<button className="primary wide" disabled={busy||(!draft.answer.trim()&&!draft.notes.trim()&&!photos.length)} onClick={()=>void submit()}><Check size={17}/>{busy?'正在保存…':'上传做题记录'}</button><small>{draft.dirty?'文字已暂存手机，上传或离开本题时同步网站。':'文字记录已与网站同步。'}</small></section>
 <section className="m-panel"><h2>已上传记录 · {records.length}</h2>{records.length===0?<p className="muted">还没有提交记录。</p>:records.map(r=><details key={r.id}><summary>{new Date(r.created_at).toLocaleString('zh-CN')} · {r.images.length} 张照片</summary><RichText text={r.answer}/><RichText text={r.reasoning}/>{r.images.map(p=><button className="m-image-button" key={p.id} onClick={()=>setImage(p.url)}><img src={p.url} alt="历史作答照片"/></button>)}</details>)}</section></div>
 {tab==='ai'&&<MobileTutor question={q} notify={notify} onOpen={onOpen}/>}
 {image&&<div className="m-lightbox" role="dialog" aria-label="原图预览"><button onClick={()=>setImage('')}>关闭原图</button><img src={image} alt="放大原图"/></div>}</>;
}

function MobileTutor({question:q,notify,onOpen}:{question:Question;notify:(s:string)=>void;onOpen:(id:string)=>void}){
 const tutor=useTutorSession<Session>(q.id,JSON.stringify([q.text,q.confirmed,q.images]));
 const {session,input,setInput,pending,sending,error,syncError,send,retryPending,refresh,reopen}=tutor;
 const [failure,setFailure]=useState('');
 const [ocr,setOcr]=useState<{text:string;fingerprint:string;uncertain:boolean}|null>(null),[scanning,setScanning]=useState(false);
 const [provider,setProvider]=useState<{configured:boolean;model_id?:string}>({configured:false});
 useEffect(()=>{void api<{configured:boolean;model_id?:string}>('/api/ai/provider').then(setProvider).catch(e=>setFailure(message(e)));},[]);
 const busy=sending||!!session?.busy||!!pending||scanning;

 return <section className="m-panel m-tutor" aria-label="手机 AI 解题"><div className="m-section-title"><h2><Sparkles size={18}/> AI 解题</h2><small>{provider.configured?provider.model_id:'请先在设置中配置 AI'}</small></div><p className="muted">说说你的思路，或让 AI 帮你分析当前这一步。</p>
 {q.images.length>0&&<button className="secondary" disabled={busy} onClick={async()=>{setScanning(true);try{setOcr(await api('/api/questions/'+q.id+'/ai/transcribe',json({})));}catch(e){setFailure(message(e));}finally{setScanning(false);}}}>{scanning?'正在识别…':'识别题图 / 核对题干'}</button>}
 {ocr&&<div><p>{ocr.uncertain?'有不确定内容，请对照上方原图核对公式。':'请对照原图确认识别题干。'}</p><textarea aria-label="识别题干" value={ocr.text} onChange={e=>setOcr({...ocr,text:e.target.value})}/><button className="primary" disabled={scanning} onClick={async()=>{setScanning(true);try{await api('/api/questions/'+q.id+'/ai/transcription',json({text:ocr.text,fingerprint:ocr.fingerprint},'PUT'));setOcr(null);await reopen();notify('题干已保存，AI 会话已更新');}catch(e){setFailure(message(e));}finally{setScanning(false);}}}>确认题干</button><button className="text-button" onClick={()=>setOcr(null)}>取消</button></div>}
 <div className="m-conversation">{session?.turns.map(t=><article key={t.id}><div className="m-user"><RichText text={t.user_text}/></div>{t.message&&<div className="m-reply"><RichText text={t.message}/></div>}{t.error&&<p className="m-error">{t.error}</p>}{t.status==='running'&&<p role="status">AI 正在分析，结果会保存在网站，可稍后回来查看…</p>}</article>)}{session?.state.cards.map(c=><div className="m-calculation" key={c.number}><b>{c.label}</b>{c.result.result_latex&&<Formula latex={c.result.result_latex}/>}<ToolVerification result={c.result}/></div>)}{session?.state.current_latex&&<Formula latex={session.state.current_latex}/ >}{session?.state.next_question&&<RichText text={session.state.next_question}/>}</div>
 {(error||syncError||failure)&&<p role="alert" className="m-error">{error||syncError||failure}</p>}{!session&&<button className="secondary" onClick={()=>void refresh()}>重试连接会话</button>}{pending&&<button className="secondary" disabled={sending} onClick={()=>void retryPending()}>核对 / 重试未确认消息</button>}{session?.stale&&<button onClick={()=>void reopen()}>题目已变更，刷新会话</button>}
 <form onSubmit={e=>{e.preventDefault();if(!ocr)void send();}}><textarea aria-label="描述解题思路" value={input} maxLength={6000} onChange={e=>setInput(e.target.value)} placeholder="我准备先…，请帮我核对这一步"/><button className="primary wide" disabled={busy||!!ocr||!provider.configured||!session||session.stale||!input.trim()}> {busy?'正在处理…':'发送给 AI'}</button></form>
 <DifficultyPanel qid={q.id} sid={session?.id} version={session?.version} busy={busy} onOpen={onOpen}/></section>;
}
