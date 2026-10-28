import {useEffect,useRef,useState} from 'react';
import {Bot,Send,Settings,X} from 'lucide-react';
import {api,json,type Question,type Result} from './types';
import {Formula,RichText} from './math';
import {APISettings} from './APISettings';
import {AnswerInput,type Spec,type Option} from './AnswerControls';
import {useTutorSession} from './useTutorSession';
import {DifficultyPanel} from './DifficultyPanel';
import {ToolVerification} from './ToolVerification';

interface Card {number:number;tool:string;label:string;input:Record<string,unknown>;result:Record<string,unknown>;valid:boolean;saved_result?:Result}
interface Turn {id:string;request_id?:string;user_text:string;message:string;status:string;error:string;created_at?:string;elapsed_seconds?:number;progress?:{phase:string;label:string};tool_errors?:{tool:string;error:string}[]}
interface Session {id:string;version:number;busy:boolean;stale:boolean;problem:{kind:string;config:Record<string,unknown>};turns:Turn[];state:{cards:Card[];next_question:string;current_latex:string;current_text:string;completed_methods:string[];completion_check:string|null;answer_exposed:boolean;final_answer?:string;final_answer_turn?:string;answer_reasoning?:string}}
interface Provider {profile_id?:string;reasoning_effort?:string;reasoning_options?:{value:string;label:string}[];reasoning_hint?:string;configured:boolean;base_url?:string;model_id?:string;model_name?:string}
interface Skill {title:string;status:string;evidence:{id:string;quote:string;reason:string;judgement:string}[]}
interface CacheInfo {enabled:boolean;entries:number;bytes:number;totals:Record<string,number>;categories:{namespace:string;hits:number;remote_calls:number}[];knowledge?:{total_questions:number;stored_questions:number;failed:number;subjects:{subject:string;questions:number}[];metrics:Record<string,number>;runs:{status:string;completed:number;total:number;failed:number}[]}}

function modelName(provider:Provider){
 if(provider.model_name)return provider.model_name;
 try{if(new URL(provider.base_url||'').hostname==='api.deepseek.com'&&provider.model_id==='deepseek-flash')return 'DeepSeek V4.1 Flash';}catch{}
 return provider.model_id;
}

function ToolValues({result}:{result:Record<string,unknown>}){
 const names:Record<string,string>={offset:'块内偏移位数',index:'组索引位数',tag:'标记位数',sets:'组数',addressable_units_per_block:'每块寻址单元数',address_offset:'块内偏移',address_index:'地址组号',address_tag:'地址标记',prefix:'前缀长度',mask:'子网掩码',mask_binary:'二进制掩码',network:'网络地址',broadcast:'广播地址',usable_hosts:'可用主机数',first_host:'首个主机地址',last_host:'末个主机地址'};
 const fields=result.fields as Record<string,unknown>|undefined;
 const solutions=result.solutions as Record<string,string>[]|undefined;
 const solutionsLatex=result.solutions_latex as Record<string,string>[]|undefined;
 const assumptions=result.assumptions as string[]|undefined;
 const trace=result.trace as Record<string,unknown>[]|undefined;
 return <><ToolVerification result={result}/>{fields&&<dl className="ai-values">{Object.entries(fields).map(([key,value])=><div key={key}><dt>{names[key]||key}</dt><dd>{String(value??'无')}</dd></div>)}</dl>}{solutionsLatex?solutionsLatex.map((s,i)=><div className="ai-solutions" key={i}><Formula latex={Object.entries(s).map(([variable,value])=>variable+' = '+value).join('\\qquad ')}/></div>):solutions?.map((s,i)=><p className="ai-solutions" key={i}>{Object.entries(s).map(([variable,value])=>variable+' = '+value).join('，')}</p>)}{solutions&&!!assumptions?.length&&<p>适用条件：{assumptions.join('；')}</p>}{trace&&<div className="ai-trace"><table><thead><tr><th>步骤</th><th>{result.frames?'访问页 / 页框':'顶点 / 距离'}</th><th>结果</th></tr></thead><tbody>{trace.map((row,i)=><tr key={i}><td>{String(row.step)}</td><td>{row.page!==undefined?<>{String(row.page)} → {(row.frames as (number|null)[]).map(v=>v??'空').join(' / ')}</>:<>{String(row.vertex)} · {Object.entries(row.distance as Record<string,unknown>).map(([k,v])=>k+': '+String(v)).join('，')}</>}</td><td>{row.fault!==undefined?(row.fault?'缺页，累计 '+String(row.fault_count):'命中'):'已访问 '+(row.visited as string[]).join('，')}</td></tr>)}</tbody></table></div>}</>;
}

export function AITutor({question,reference,onClose,onInsert,onSelect,onChanged,onAnswer,notify,answerInfo,selectedAnswer,onSelectAnswer,onOpenGrading,answerDialogOpen}:{question:Question;reference:boolean;onClose:()=>void;onInsert:(r:Result)=>void;onSelect:(id:string)=>void;onChanged:()=>void;onAnswer:(answer:string,reasoning:string)=>void;notify:(s:string)=>void;answerInfo:{spec:Spec;options:Option[]}|null;selectedAnswer:string;onSelectAnswer:(s:string)=>void;onOpenGrading:()=>void;answerDialogOpen:boolean}){
 const {session,setSession,error,setError,sending,input,setInput,pending,syncError,refreshing,refresh,retryPending,send:sendTurn,reopen,clock}=useTutorSession<Session>(question.id,JSON.stringify([question.text,question.confirmed,question.images]));
 const [provider,setProvider]=useState<Provider>({configured:false}),[settings,setSettings]=useState(false),[changingReasoning,setChangingReasoning]=useState(false);
 const [skills,setSkills]=useState<Skill[]>([]),[learning,setLearning]=useState(false);
 const [cacheInfo,setCacheInfo]=useState<CacheInfo|null>(null),[cacheOpen,setCacheOpen]=useState(false);
 const [ocr,setOcr]=useState<{text:string;fingerprint:string;uncertain:boolean}|null>(null),[scanning,setScanning]=useState(false);
 const mounted=useRef(true),end=useRef<HTMLDivElement>(null),autoScan=useRef('');
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 function report(e:unknown){if(mounted.current)setError((e as Error).message);}
 async function loadCache(){try{const value=await api<CacheInfo>('/api/ai/cache');if(mounted.current)setCacheInfo(value);}catch{}}
 useEffect(()=>{if(!session?.busy&&!scanning)void loadCache();},[session?.version,session?.busy,scanning]);
 useEffect(()=>{if(!cacheOpen)return;const timer=setInterval(()=>void loadCache(),5000);return()=>clearInterval(timer);},[cacheOpen]);
 useEffect(()=>{
  let live=true;
  api<Provider>('/api/ai/provider').then(p=>{if(live)setProvider(p);}).catch(report);
  return()=>{live=false;};
 },[question.id,question.text,question.confirmed,question.images.join('|')]);
 useEffect(()=>{
  if(!provider.configured||!question.images.length||!(/请阅读下方原始题图|公式以图片为准|扫描题目/.test(question.text))||autoScan.current===question.id)return;
  autoScan.current=question.id;
  void scan();
 },[provider.configured,question.id,question.text]);
 const syncedAnswer=useRef<string|null>(null);
 useEffect(()=>{if(!session)return;const token=session.state.final_answer_turn||'';if(syncedAnswer.current===null){syncedAnswer.current=token;return;}if(token&&token!==syncedAnswer.current&&session?.state.final_answer){syncedAnswer.current=token;onAnswer(session.state.final_answer,session.state.answer_reasoning||'');}},[session?.id,session?.state.final_answer_turn]);
 useEffect(()=>{end.current?.scrollIntoView({block:'nearest'});},[session?.turns.length,session?.version]);
 useEffect(()=>{
  if(!reference||!session||session.state.answer_exposed)return;
  let live=true;
  api<Session>('/api/ai/sessions/'+session.id+'/answer-exposed',json({})).then(s=>{if(live)setSession(s);}).catch(report);
  return()=>{live=false;};
 },[reference,session?.id,session?.busy,session?.state.answer_exposed]);
 async function send(text=input){
  if(scanning||ocr||changingReasoning||!provider.configured)return;
  await sendTurn(text);
 }

 async function scan(){setScanning(true);try{setOcr(await api('/api/questions/'+question.id+'/ai/transcribe',json({})));}catch(e){report(e);}finally{setScanning(false);}}
 async function confirmOcr(){if(!ocr)return;try{await api('/api/questions/'+question.id+'/ai/transcription',json({fingerprint:ocr.fingerprint,text:ocr.text},'PUT'));setOcr(null);onChanged();notify('题干已保存到原题库');}catch(e){report(e);}}
 const busy=sending||!!session?.busy||!!pending||changingReasoning;
 const last=session?.turns.at(-1),unconfirmed=!!pending&&!session?.turns.some(t=>t.request_id===pending.request_id);
 const elapsed=last?.created_at?Math.max(last.elapsed_seconds||0,Math.floor((clock-Date.parse(last.created_at))/1000)):last?.elapsed_seconds||0;
 const status=unconfirmed?'发送结果待确认':session?.busy?(last?.progress?.label||'正在分析和代算'):last?.status==='complete'?'回复已完成并保存':last?.status==='failed'?'本轮失败，输入已保留':last?.status==='cancelled'?'已停止，输入已保留':session?'可以继续描述思路':'正在读取会话记录';
 return <section className="ai-tutor pane" aria-label="AI 解题">
  <div className="pane-heading"><span><Bot size={17}/>AI 解题</span><div><button className="text-button" aria-label="AI 模型设置" onClick={()=>setSettings(v=>!v)}><Settings size={16}/></button><button className="text-button" aria-label="收起 AI 解题" onClick={onClose}><X size={17}/></button></div></div>
  <div className="ai-model"><span>{provider.configured?modelName(provider):'请设置 AI 模型'}</span>{provider.configured&&provider.reasoning_options&&<label className="ai-reasoning">思考强度<select aria-label="思考强度" title={provider.reasoning_hint} value={provider.reasoning_effort||'default'} disabled={busy||scanning} onChange={async e=>{setChangingReasoning(true);try{setProvider(await api<Provider>('/api/ai/provider/reasoning',json({profile_id:provider.profile_id,reasoning_effort:e.target.value},'PUT')));notify('思考强度已保存，下一次请求生效');}catch(e){report(e);}finally{setChangingReasoning(false);}}}>{provider.reasoning_options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>}<button className="text-button" aria-expanded={cacheOpen} onClick={()=>{setCacheOpen(v=>!v);void loadCache();}}>本地缓存</button>{question.images.length>0&&<button className="text-button" disabled={scanning||busy} onClick={scan}>{scanning?'识别中…':'识别题图'}</button>}<button className="text-button" onClick={async()=>{setLearning(v=>!v);try{setSkills(await api('/api/ai/learning'));}catch(e){report(e);}}}>学习记录</button></div>
  {cacheOpen&&<div className="ai-cache-panel"><b>本地缓存{cacheInfo?.enabled?'已开启':''}</b>{cacheInfo?.enabled?<>{cacheInfo.knowledge&&<div className="ai-knowledge-info"><b>试卷预解析库 · 已存 {cacheInfo.knowledge.stored_questions} / {cacheInfo.knowledge.total_questions} 题</b><p>{cacheInfo.knowledge.subjects.map(s=>s.subject+' '+s.questions+'题').join(' · ')}</p>{cacheInfo.knowledge.runs[0]?.status==='running'&&<p>后台解析中：{cacheInfo.knowledge.runs[0].completed} / {cacheInfo.knowledge.runs[0].total}</p>}<small>预解析长期保存，清空下面的临时缓存会保留它。题目或参考答案修改后会重新匹配版本。</small></div>}<p>已存 {cacheInfo.entries} 条 · {(cacheInfo.bytes/1024/1024).toFixed(2)} MB</p><p>累计复用模型请求 {cacheInfo.categories.filter(c=>c.namespace!=='tools').reduce((n,c)=>n+c.hits,0)} 次 · 减少输入 {cacheInfo.totals.avoided_prompt_tokens||0} tokens</p><p>DeepSeek 服务端缓存命中 {cacheInfo.totals.provider_cached_tokens||0} tokens</p><small>新步骤使用精简上下文；重复题图和相同请求可直接复用。清空只删除缓存结果。</small><div className="toolbar"><button className="text-button" onClick={()=>void loadCache()}>刷新统计</button><button className="text-button" disabled={busy||scanning} onClick={async()=>{try{setCacheInfo(await api<CacheInfo>('/api/ai/cache',{method:'DELETE'}));notify('本地缓存已清空');}catch(e){report(e);}}}>清空缓存</button></div></>:<p>缓存状态暂不可用，请稍后刷新。</p>}</div>}
  {!provider.configured&&!settings&&<button className="secondary" onClick={()=>setSettings(true)}>填写模型地址和 API 密钥</button>}
  {settings&&<div className="ai-settings"><APISettings notify={notify} onChanged={()=>{void api<Provider>('/api/ai/provider').then(setProvider).catch(report);}} onClose={()=>setSettings(false)}/></div>}
  {learning&&<div className="ai-learning"><button className="text-button" onClick={()=>setLearning(false)}>收起学习记录</button>{skills.length?skills.map(s=><div key={s.title}><b>{s.title} · {s.status}</b>{s.evidence.map(e=><p key={e.id}>“{e.quote}” · {e.reason}<button className="text-button" onClick={async()=>{try{await api('/api/ai/observations/'+e.id+'/exclude',json({}));setSkills(await api('/api/ai/learning'));}catch(ex){report(ex);}}}>撤销判断</button></p>)}</div>):<p>你说出的判断会逐步记录。委托计算不算薄弱项。</p>}</div>}
  {scanning&&<p role="status" className="ai-review">正在读取当前题图…</p>}
  {ocr&&<div className="ai-ocr"><b>对照左侧原图，确认题干</b>{ocr.uncertain&&<p>识别有不确定内容，请核对公式。</p>}<textarea aria-label="AI 识别题干" value={ocr.text} onChange={e=>setOcr({...ocr,text:e.target.value})}/><button className="primary small" onClick={confirmOcr}>确认并保存到题库</button><button className="text-button" onClick={()=>setOcr(null)}>取消</button></div>}
  <div className="ai-conversation" aria-live="polite">
   {!answerDialogOpen&&answerInfo&&<div className="ai-answer-selector"><AnswerInput spec={answerInfo.spec} value={selectedAnswer} onChange={onSelectAnswer} label="AI 解题答案" disabled={busy}/><div className="ai-answer-actions"><button className="secondary small" disabled={busy||!selectedAnswer.trim()||!provider.configured} onClick={()=>send((answerInfo.spec.kind==='mcq'?'我选择 '+selectedAnswer+'。':'我的答案是 '+selectedAnswer+'。')+'请根据我目前说出的思路，引导我核对理由，不要直接公布参考答案。')}>按此答案继续分析</button><button className="secondary small" onClick={onOpenGrading}>提交答案 / 图片批改</button></div></div>}

   {!question.confirmed&&<p className="ai-review">本题尚未校对，先对照原图确认公式；本次过程暂不计入薄弱项。</p>}
   {session?.turns.length===0&&<p className="muted">说说这道题准备怎么做。需要笔算时直接让我算。</p>}
   {session?.turns.map(t=><div className="ai-turn" key={t.id}><div className="ai-user"><RichText text={t.user_text}/></div>{t.message&&<div className="ai-response"><RichText text={t.message}/></div>}{t.error&&<p className="ai-error">{t.error}<button className="text-button" disabled={busy} onClick={()=>send(t.user_text)}>重试</button></p>}{t.tool_errors?.length?<div className="ai-error">部分代算未完成：{t.tool_errors.map(e=><p key={e.tool+e.error}>{e.tool}：{e.error}</p>)}</div>:null}{t.status==='running'&&<p>{t.progress?.label||'正在分析和代算'}…</p>}</div>)}
   {unconfirmed&&pending&&<div className="ai-turn"><div className="ai-user"><RichText text={pending.text}/></div><p>正在核对这条消息是否已被后台接收，请勿重复输入。</p></div>}
   {!!session?.state.cards.length&&<details className="ai-cards" open><summary>本题代算草稿 · {session.state.cards.length} 步</summary>{session.state.cards.map(c=><article key={c.number} className={c.valid?'':'ai-invalid'}><b>{c.number}. {c.label||c.tool}{!c.valid&&'（已修订）'}</b>{!!c.result.result_latex&&<Formula latex={String(c.result.result_latex)}/>}<ToolValues result={c.result}/><details><summary>计算参数与结果</summary><pre>{JSON.stringify({input:c.input,...c.result},null,2)}</pre></details>{c.saved_result&&c.valid&&<button className="text-button" onClick={()=>onInsert(c.saved_result!)}>写入本题笔记</button>}</article>)}</details>}
   {session?.state.current_latex&&<div className="ai-current"><small>当前一步</small><Formula latex={session.state.current_latex}/></div>}
   {session&&!session.busy&&session.state.next_question&&<div className="ai-next"><RichText text={session.state.next_question}/></div>}
   {session?.problem.kind!=='scratch'&&session?.problem.config&&<details className="ai-structure"><summary>核对 AI 读取的原式</summary><pre>{JSON.stringify(session.problem.config,null,2)}</pre><button className="text-button" onClick={()=>notify('公式有误时，请在左侧“编辑题目”中修正题干，或点击“识别题图”核对。')}>公式有误</button></details>}
   <DifficultyPanel qid={question.id} sid={session?.id} version={session?.version} busy={busy||scanning} onOpen={onSelect}/>
   <div ref={end}/>
  </div>
  <div className={'ai-request-status '+(syncError||unconfirmed?'uncertain':last?.status==='failed'?'failed':'')} role="status"><span>{status}{session?.busy&&' · 已等待 '+elapsed+' 秒'}</span><button className="text-button" disabled={refreshing} onClick={()=>void refresh()}>{refreshing?'核对中…':'刷新结果'}</button>{unconfirmed&&<button className="text-button" disabled={sending||refreshing} onClick={()=>void retryPending()}>核对并重试发送</button>}</div>
  {syncError&&<p className="ai-error" role="alert">暂时无法读取后台结果：{syncError}。会自动重连，也可点击“刷新结果”。输入已保留。</p>}
  {session?.stale&&<p className="ai-review">题目已更新，旧对话仍然保留。<button className="text-button" disabled={!!session.busy} onClick={()=>void reopen()}>重新打开当前题目</button></p>}
  {error&&<p className="ai-error" role="alert">{error}</p>}
  <div className="ai-input"><textarea aria-label="描述解题思路" placeholder="我想用泰勒展开，先比较分子分母…" value={input} disabled={busy} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><div className="ai-actions"><div><button className="text-button" disabled={busy||scanning||!!ocr||!provider.configured} onClick={()=>send('给我当前这一步的一点提示，不要直接给答案')}>提示</button>{!!session?.state.completed_methods.length&&<button className="text-button" disabled={busy} onClick={()=>send('再用另一种方法解原题，先只引导我完成第一步')}>练另一解法</button>}</div>{session?.busy?<button className="secondary small" onClick={async()=>{if(session)try{await api('/api/ai/sessions/'+session.id+'/cancel',json({}));}catch(e){report(e);}}}>停止</button>:<button className="primary small" disabled={busy||!session||!input.trim()||!provider.configured||session.stale||scanning||!!ocr} onClick={()=>send()}><Send size={14}/>发送</button>}</div></div>
 </section>;
}
