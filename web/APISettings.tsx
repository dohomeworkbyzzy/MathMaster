import {useEffect,useState} from 'react';
import {Check,Plus,Settings2,Trash2,X} from 'lucide-react';
import {api,json} from './types';

type Kind='chat'|'embedding';
interface ReasoningOption {value:string;label:string}
interface ReasoningInfo {reasoning_options:ReasoningOption[];reasoning_hint:string}
interface Profile {reasoning_effort?:string;reasoning_options?:ReasoningOption[];id:string;kind:Kind;provider_name:string;base_url:string;model_id:string;protocol:string;has_api_key:boolean;timeout:number;extra_body:Record<string,unknown>}
interface Registry {read_only?:boolean;can_activate?:boolean;profiles:Profile[];active_chat:string|null;active_embedding:string;auto_index:boolean}
interface Job {id:string;status:string;phase:string;total:number;completed:number;failed:number;error:string}
interface IndexStatus {indexed:number;total:number;dimensions:number|null;model:string;ready:boolean;local:boolean;auto_index:boolean;jobs:Job[]}
interface Form {reasoning_effort:string;id?:string;kind:Kind;provider_name:string;base_url:string;model_id:string;protocol:string;api_key:string;timeout:number;options:string}
const blank=(kind:Kind):Form=>({kind,provider_name:'',base_url:'',model_id:'',protocol:kind==='chat'?'openai_chat_completions':'openai_embeddings',api_key:'',timeout:60,options:'{}',reasoning_effort:'default'});

export function APISettings({notify,onChanged,onClose}:{notify:(s:string)=>void;onChanged?:()=>void;onClose?:()=>void}){
 const [reasoning,setReasoning]=useState<ReasoningInfo|null>(null);
 const [registry,setRegistry]=useState<Registry|null>(null),[status,setStatus]=useState<IndexStatus|null>(null),[kind,setKind]=useState<Kind>('chat');
 const [form,setForm]=useState<Form|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[models,setModels]=useState<string[]>([]);
 async function refresh(){try{const value=await api<Registry>('/api/ai/profiles');setRegistry(value);if(!value.read_only)setStatus(await api<IndexStatus>('/api/ai/embeddings/status'));}catch(e){setError((e as Error).message);}}
 useEffect(()=>{
  if(!form||form.kind!=='chat'){setReasoning(null);return;}
  let live=true;const timer=setTimeout(()=>{void api<ReasoningInfo>('/api/ai/reasoning/options?'+new URLSearchParams({model_id:form.model_id,protocol:form.protocol})).then(value=>{if(live)setReasoning(value);}).catch(e=>{if(live)setError(e.message);});},250);
  return()=>{live=false;clearTimeout(timer);};
 },[form?.model_id,form?.protocol,form?.kind]);
 useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>clearInterval(timer);},[]);
 async function action(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();onChanged?.();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 function edit(p:Profile){setModels([]);setForm({id:p.id,kind:p.kind,provider_name:p.provider_name,base_url:p.base_url,model_id:p.model_id,protocol:p.protocol,timeout:p.timeout,api_key:'',options:JSON.stringify(p.extra_body,null,2),reasoning_effort:p.reasoning_effort||'default'});}
 function preset(value:string){const f=blank(kind);if(value==='deepseek')Object.assign(f,{provider_name:'DeepSeek V4.1 Flash',base_url:'https://api.deepseek.com',model_id:'deepseek-flash'});if(value==='openai')Object.assign(f,{provider_name:kind==='chat'?'OpenAI':'OpenAI Embedding',base_url:'https://api.openai.com/v1',model_id:kind==='embedding'?'text-embedding-3-small':''});if(value==='anthropic')Object.assign(f,{provider_name:'Anthropic',base_url:'https://api.anthropic.com/v1',protocol:'anthropic_messages'});setForm(f);setModels([]);}
 async function save(activate:boolean){if(!form)return;await action(async()=>{
  const extra_body=JSON.parse(form.options);if(typeof extra_body!=='object'||!extra_body||Array.isArray(extra_body))throw new Error('高级参数须为 JSON 对象。');
  const {options,...body}=form;const saved=await api<Registry>('/api/ai/profiles',json({...body,extra_body}));
  const id=form.id||saved.profiles.find(p=>!registry?.profiles.some(old=>old.id===p.id))?.id;
  if(activate&&id)await api('/api/ai/profiles/'+id+'/activate',json({}));
  setForm(null);await refresh();notify(activate?'配置已保存并启用':'配置已保存');
 });}
 const active=kind==='chat'?registry?.active_chat:registry?.active_embedding;
 if(!registry)return <section className="provider-board" aria-label="API 可视化配置"><div className="provider-heading"><h2><Settings2 size={20}/> API 配置</h2>{onClose&&<button className="icon-button" aria-label="关闭 API 配置" onClick={onClose}><X size={18}/></button>}</div><p>{error||'读取模型名称…'}</p></section>;
 if(registry.read_only)return <section className="provider-board" aria-label="API 可视化配置"><div className="provider-heading"><div><h2><Settings2 size={20}/> API 配置</h2><p>外网访问仅显示模型名称</p></div>{onClose&&<button className="icon-button" aria-label="关闭 API 配置" onClick={onClose}><X size={18}/></button>}</div>{error&&<p role="alert" className="ai-error">{error}</p>}<div className="provider-cards">{registry.profiles.map(p=>{const selected=p.id===(p.kind==='chat'?registry.active_chat:registry.active_embedding);return <article key={p.id} className={'provider-card '+(selected?'selected':'')}><div className="provider-card-title"><b>{p.model_id}</b>{selected&&<span><Check size={14}/>使用中</span>}</div>{registry.can_activate&&<button className="primary small" disabled={busy||selected} onClick={()=>action(async()=>{setRegistry(await api<Registry>('/api/ai/profiles/'+encodeURIComponent(p.id)+'/activate',json({})));notify('已切换模型');})}>{selected?'已启用':'启用'}</button>}</article>;})}</div></section>;
 return <section className="provider-board" aria-label="API 可视化配置"><div className="provider-heading"><div><h2><Settings2 size={20}/> API 配置</h2><p>保存多套配置，一键切换。密钥只保存在本机后端。</p></div>{onClose&&<button className="icon-button" aria-label="关闭 API 配置" onClick={onClose}><X size={18}/></button>}</div>
  <div className="provider-tabs"><button className={kind==='chat'?'active':''} onClick={()=>{setKind('chat');setForm(null);}}>解题模型</button><button className={kind==='embedding'?'active':''} onClick={()=>{setKind('embedding');setForm(null);}}>知识向量 / Embedding</button></div>
  {error&&<p role="alert" className="ai-error">{error}</p>}
  <div className="provider-cards">{registry?.profiles.filter(p=>p.kind===kind).map(p=><article key={p.id} className={'provider-card '+(p.id===active?'selected':'')}><div className="provider-card-title"><b>{p.provider_name}</b>{p.id===active&&<span><Check size={14}/>使用中</span>}</div><code>{p.model_id}</code><small>{p.protocol==='local_bge'?'本地 CPU · 免费 · 中文 512 维':p.protocol==='anthropic_messages'?'Anthropic Messages':'OpenAI '+(kind==='embedding'?'Embeddings':'Chat Completions')}</small>{p.kind==='chat'&&<small>思考强度：{p.reasoning_options?.find(o=>o.value===(p.reasoning_effort||'default'))?.label||'默认'}</small>}{p.base_url&&<small className="provider-url">{p.base_url}</small>}
   <div className="toolbar"><button className="primary small" disabled={busy||p.id===active} onClick={()=>action(async()=>{setRegistry(await api<Registry>('/api/ai/profiles/'+p.id+'/activate',json({})));await refresh();notify(kind==='embedding'?'已切换向量模型，索引任务已排队':'已切换解题模型');})}>{p.id===active?'已启用':'启用'}</button>
    <button className="secondary small" disabled={busy} onClick={()=>action(async()=>{const result=await api<{dimensions?:number}>('/api/ai/profiles/'+p.id+'/test',json({}));notify('连接成功'+(result.dimensions?' · '+result.dimensions+' 维':''));})}>测试</button>
    {p.protocol!=='local_bge'&&<><button className="text-button" disabled={busy} onClick={()=>edit(p)}>编辑</button><button className="icon-button" aria-label={'删除 '+p.provider_name} disabled={busy||p.id===active} onClick={()=>action(async()=>{setRegistry(await api<Registry>('/api/ai/profiles/'+p.id,{method:'DELETE'}));})}><Trash2 size={14}/></button></>}
   </div></article>)}</div>
  {!form&&<button className="secondary" disabled={busy} onClick={()=>{setForm(blank(kind));setModels([]);}}><Plus size={16}/>新增{kind==='chat'?'解题':'向量'}配置</button>}
  {form&&<form className="provider-form" onSubmit={e=>{e.preventDefault();void save(false);}}><div className="provider-form-head"><b>{form.id?'编辑配置':'新增配置'}</b>{!form.id&&<select aria-label="供应商预设" defaultValue="custom" onChange={e=>preset(e.target.value)}><option value="custom">自定义 / 中转站</option><option value="openai">OpenAI</option>{kind==='chat'&&<><option value="deepseek">DeepSeek V4.1 Flash</option><option value="anthropic">Anthropic</option></>}</select>}</div>
   <label>配置名称<input aria-label="配置名称" required value={form.provider_name} onChange={e=>setForm({...form,provider_name:e.target.value})}/></label>
   <label>协议<select aria-label="API 协议" value={form.protocol} onChange={e=>setForm({...form,protocol:e.target.value,reasoning_effort:'default'})}>{kind==='chat'?<><option value="openai_chat_completions">OpenAI Chat Completions</option><option value="anthropic_messages">Anthropic Messages</option></>:<option value="openai_embeddings">OpenAI Embeddings</option>}</select></label>
   <label>接口地址<input aria-label="接口地址" required value={form.base_url} placeholder="https://…/v1" onChange={e=>setForm({...form,base_url:e.target.value})}/></label>
   <label>模型名称<div className="provider-model"><input aria-label="模型名称" list="provider-model-list" required value={form.model_id} onChange={e=>setForm({...form,model_id:e.target.value,reasoning_effort:'default'})}/>{form.id&&<button type="button" className="secondary small" disabled={busy} onClick={()=>action(async()=>setModels((await api<{models:string[]}>('/api/ai/profiles/'+form.id+'/models')).models))}>获取模型</button>}</div><datalist id="provider-model-list">{models.map(m=><option key={m} value={m}/>)}</datalist></label>
   {form.kind==='chat'&&<label>思考强度<select aria-label="配置思考强度" value={form.reasoning_effort} onChange={e=>setForm({...form,reasoning_effort:e.target.value})}>{(reasoning?.reasoning_options||[{value:'default',label:'默认'}]).map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select><small>{reasoning?.reasoning_hint||'读取模型支持的档位…'}</small></label>}
   <label>API 密钥<input aria-label="API 密钥" type="password" autoComplete="new-password" value={form.api_key} placeholder={form.id?'留空保留原密钥':'输入本机密钥'} onChange={e=>setForm({...form,api_key:e.target.value})}/></label>
   <details><summary>高级设置</summary><label>超时（秒）<input type="number" min={5} max={300} value={form.timeout} onChange={e=>setForm({...form,timeout:Number(e.target.value)})}/></label><label>额外请求参数（JSON）<textarea aria-label="额外请求参数" value={form.options} onChange={e=>setForm({...form,options:e.target.value})}/></label></details>
   <div className="toolbar"><button className="primary" disabled={busy} type="submit">保存配置</button><button className="secondary" disabled={busy} type="button" onClick={()=>save(true)}>保存并启用</button><button className="text-button" type="button" onClick={()=>setForm(null)}>取消</button></div>
  </form>}
  {kind==='embedding'&&<p className="muted">解题 API 与向量 API 独立。Anthropic 没有内置 embedding 接口，可搭配内置中文模型或 OpenAI 兼容向量服务。</p>}
  <div className="vector-status"><div className="provider-heading"><div><b>知识向量库</b><p>{status?`${status.indexed} / ${status.total} 题 · ${status.model}${status.dimensions?' · '+status.dimensions+' 维':''}`:'读取索引状态…'}</p></div><button className="secondary small" disabled={busy} onClick={()=>action(async()=>{await api('/api/ai/embeddings/rebuild',json({}));await refresh();notify('索引任务已排队；已有且未变化的题目会直接复用');})}>补全 / 重试索引</button></div>
   <label className="vector-auto"><input type="checkbox" checked={registry?.auto_index??true} disabled={busy} onChange={e=>action(async()=>{setRegistry(await api<Registry>('/api/ai/embeddings/auto',json({enabled:e.target.checked},'PUT')));await refresh();})}/>新试卷自动预解析并建立知识向量</label>
   {status&&!status.ready&&<p className="ai-error">当前向量模型尚未准备好，请测试并检查配置。</p>}
   {status?.jobs.map(j=><div className="vector-job" key={j.id}><span>{({queued:'排队中',running:'进行中',complete:'完成',failed:'失败'} as Record<string,string>)[j.status]||j.status} · {j.phase}</span><span>{j.completed} / {j.total}</span>{j.error&&<p>{j.error}</p>}</div>)}
  </div>
 </section>;
}

interface Match {question_id:string;number:string;paper_title:string;subject:string;topic:string;score:number;reason:string}
export function SimilarQuestions({onSelect,notify}:{onSelect:(id:string)=>void;notify:(s:string)=>void}){
 const [text,setText]=useState(''),[subject,setSubject]=useState('数学二'),[items,setItems]=useState<Match[]>([]),[busy,setBusy]=useState(false),[searched,setSearched]=useState(false),[reason,setReason]=useState('');
 async function search(){setBusy(true);try{const r=await api<{items:Match[];reason:string}>('/api/ai/similar?'+new URLSearchParams({text,subject}));setItems(r.items);setReason(r.reason);setSearched(true);}catch(e){notify((e as Error).message);}finally{setBusy(false);}}
 return <section className="provider-board"><p className="muted">描述考察的知识方向或想练习的方法，例如“泰勒展开判断等价无穷小”“Cache 地址划分”“进程互斥与同步”。</p><form className="vector-search" onSubmit={e=>{e.preventDefault();void search();}}><select aria-label="相似题科目" value={subject} onChange={e=>setSubject(e.target.value)}><option>数学二</option><option>408</option><option>数学一</option><option value="">全部科目</option></select><input aria-label="检索知识方向" value={text} maxLength={2000} onChange={e=>setText(e.target.value)} placeholder="想练习什么知识点？"/><button className="primary" disabled={busy||!text.trim()}>{busy?'检索中…':'查找相似题'}</button></form>
  {searched&&<p className="muted">{items.length?'找到 '+items.length+' 道相关题；得分用于排序。':reason}</p>}
  <div className="vector-matches">{items.map(m=><article key={m.question_id}><div><b>{m.paper_title} · 第 {m.number} 题</b><p>{m.topic}</p><small>{m.reason}</small></div><button className="secondary" onClick={()=>onSelect(m.question_id)}>开始练习</button></article>)}</div>
 </section>;
}
