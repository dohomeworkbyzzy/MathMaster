import {randomId} from './ids';
import {useEffect,useId,useRef,useState} from 'react';
import {api,json} from './types';
import {RichText} from './math';

export type Criterion={id:string;description:string;max_points:number;depends_on?:string[];mode?:'partial'|'all_or_nothing'};
export type Rules={instructions:string;source:string;verified:boolean;criteria:Criterion[]};
export type Spec={kind:string;max_points:number;points_known?:boolean;source?:string;reference_pdf?:string;reference_images?:string[];reference_issue?:string;scoring_rules?:Rules};
export type Option={value:string;text:string};
export type Photo={id:string;url:string;width:number;height:number;sha256:string};
type PhotoDraft={version:number;images:Photo[]};

export function AnswerInput({spec,value,onChange,label='记录的答案',options=[],disabled=false}:{spec:Spec;value:string;onChange:(s:string)=>void;label?:string;options?:Option[];disabled?:boolean}){
 const name=useId();
 return <div className="grading-answer"><div className="field-label">{label}</div>{spec.kind==='mcq'?<div role="radiogroup" aria-label={label} className={'answer-choices '+(options.some(o=>o.text)?'with-option-text':'')}>{['A','B','C','D'].map(v=>{const text=options.find(o=>o.value===v)?.text;return <label key={v} className={value===v?'chosen':''}><input type="radio" aria-label={v} name={name} value={v} disabled={disabled} checked={value.toUpperCase().trim()===v} onChange={()=>onChange(v)}/><b>{v}</b>{text&&<RichText text={text}/>}</label>;})}<button type="button" className="text-button" disabled={disabled} onClick={()=>onChange('')}>清空</button></div>:<textarea aria-label={label} value={value} disabled={disabled} placeholder={spec.kind==='fill'?'填写各空的最终答案；公式支持 $LaTeX$':'填写最终答案；关键步骤写在解题过程中，也可以上传图片'} onChange={e=>onChange(e.target.value)}/>}</div>;
}

export function usePhotoDraft(qid:string,notify:(s:string)=>void){
 const [draft,setDraft]=useState<PhotoDraft>({version:0,images:[]}),[saving,setSaving]=useState(false),[loaded,setLoaded]=useState(false);
 const latest=useRef(draft);latest.current=draft;const chain=useRef(Promise.resolve());
 useEffect(()=>{
  let live=true;setLoaded(false);
  api<PhotoDraft>('/api/grading/questions/'+qid+'/draft').then(d=>{if(live){latest.current=d;setDraft(d);setLoaded(true);}}).catch(e=>notify(e.message));
  function event(e:Event){const d=(e as CustomEvent<{qid:string;draft:PhotoDraft}>).detail;if(d.qid===qid&&d.draft.version>=latest.current.version){latest.current=d.draft;setDraft(d.draft);}}
  window.addEventListener('mathmaster-answer-photos',event);return()=>{live=false;window.removeEventListener('mathmaster-answer-photos',event);};
 },[qid]);
 async function save(images:Photo[]){setSaving(true);chain.current=chain.current.catch(()=>{}).then(async()=>{const d=await api<PhotoDraft>('/api/grading/questions/'+qid+'/draft',json({version:latest.current.version,images:images.map(p=>p.id)},'PUT'));latest.current=d;setDraft(d);window.dispatchEvent(new CustomEvent('mathmaster-answer-photos',{detail:{qid,draft:d}}));});try{await chain.current;}finally{setSaving(false);}}
 return {images:draft.images,save,saving,loaded};
}

export function AnswerPhotos({qid,images,onChange,notify,disabled=false,label='上传作答图片',onBusy}:{qid:string;images:Photo[];onChange:(p:Photo[])=>Promise<void>|void;notify:(s:string)=>void;disabled?:boolean;label?:string;onBusy?:(b:boolean)=>void}){
 const [busy,setBusy]=useState(false);
 async function upload(files:FileList|null){if(!files?.length)return;setBusy(true);onBusy?.(true);const next=[...images];try{
  if(next.length+files.length>5)throw new Error('每题最多五张作答图片。');
  for(const file of Array.from(files)){if(file.size>10*1024*1024)throw new Error('每张图片最多 10 MB。');const form=new FormData();form.append('file',file);next.push(await api<Photo>('/api/grading/questions/'+qid+'/images',{method:'POST',body:form}));}
  await onChange(next);
 }catch(e){notify((e as Error).message);if(next.length>images.length)try{await onChange(next);}catch{}}finally{setBusy(false);onBusy?.(false);}}
 return <div className="answer-photos"><label className="answer-upload"><span>{busy?'上传并保存中…':label}</span><input aria-label={label} type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={busy||disabled||images.length>=5} onChange={e=>{const files=e.target.files;void upload(files);e.target.value='';}}/></label><small>填空或手写过程均可 · 最多五张，单张 10 MB</small><PhotoView images={images} onRemove={!disabled&&!busy?async id=>{try{await onChange(images.filter(p=>p.id!==id));}catch(e){notify((e as Error).message);}}:undefined}/></div>;
}

export function PhotoView({images,onRemove}:{images:Photo[];onRemove?:(id:string)=>void}){
 return <div className="answer-photo-list">{images.map((p,i)=><div key={p.id}><a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={'作答图片 '+(i+1)}/></a>{onRemove&&<button className="text-button" type="button" onClick={()=>onRemove(p.id)}>移除第 {i+1} 张</button>}</div>)}</div>;
}

export function RubricEditor({qid,spec,onSaved,notify}:{qid:string;spec:Spec;onSaved:(s:Spec)=>void;notify:(s:string)=>void}){
 const initial=spec.scoring_rules;const [editing,setEditing]=useState(false),[rules,setRules]=useState<Rules>(initial||{instructions:'',source:'用户录入并核对的评分要求',verified:false,criteria:[]}),[busy,setBusy]=useState(false);
 useEffect(()=>setRules(spec.scoring_rules||{instructions:'',source:'用户录入并核对的评分要求',verified:false,criteria:[]}),[qid,spec]);
 const total=rules.criteria.reduce((s,c)=>s+c.max_points,0);
 async function save(){setBusy(true);try{const result=await api<{spec:Spec}>('/api/grading/questions/'+qid+'/rules',json(rules,'PUT'));onSaved(result.spec);setEditing(false);notify('评分要求已保存，后续批改按这些评分点执行');}catch(e){notify((e as Error).message);}finally{setBusy(false);}}
 return <details className="grading-rules"><summary>评分要求 · {initial?.criteria.length?(initial.verified?'已核对，逐点评分':'未核对，参考估分'):'参考答案估分'}</summary>{!editing?<><p className="muted">{initial?.instructions||'本题未录入完整评分细则，AI 会依据参考答案估分；有细则时可补充逐项分值。'}</p>{initial?.criteria.map(c=><p key={c.id}>{c.description}（{c.max_points} 分）</p>)}<button className="secondary small" onClick={()=>setEditing(true)}>编辑评分要求</button></>:<div className="rubric-editor"><label>评分说明<textarea aria-label="评分说明与要求" value={rules.instructions} onChange={e=>setRules({...rules,instructions:e.target.value})} placeholder="例如不同解法按等价步骤给分，最终数值错误扣结论分。"/></label><label>依据来源<input aria-label="评分要求来源" value={rules.source} onChange={e=>setRules({...rules,source:e.target.value})}/></label>{rules.criteria.map((c,i)=><div className="rubric-row" key={c.id}><b>第 {i+1} 点</b><textarea aria-label={'评分点 '+(i+1)} value={c.description} placeholder="此步骤的得分条件" onChange={e=>setRules({...rules,criteria:rules.criteria.map((r,n)=>n===i?{...r,description:e.target.value}:r)})}/><input aria-label={'评分点分值 '+(i+1)} type="number" min={.5} max={spec.max_points} step=".5" value={c.max_points} onChange={e=>setRules({...rules,criteria:rules.criteria.map((r,n)=>n===i?{...r,max_points:Number(e.target.value)}:r)})}/><button className="text-button" onClick={()=>setRules({...rules,criteria:rules.criteria.filter(r=>r.id!==c.id).map(r=>({...r,depends_on:r.depends_on?.filter(d=>d!==c.id)}))})}>移除</button><label className="rule-mode"><input type="checkbox" checked={c.mode==='all_or_nothing'} onChange={e=>setRules({...rules,criteria:rules.criteria.map((r,n)=>n===i?{...r,mode:e.target.checked?'all_or_nothing':'partial'}:r)})}/>此评分点只给全分或零分</label></div>)}<button className="secondary small" onClick={()=>setRules({...rules,criteria:[...rules.criteria,{id:'P'+randomId().slice(0,6),description:'',max_points:Math.max(.5,spec.max_points-total)}]})}>添加评分点</button><p>评分点合计 {total} / {spec.max_points} 分</p><label className="rubric-verified"><input type="checkbox" checked={rules.verified} onChange={e=>setRules({...rules,verified:e.target.checked})}/>已核对这些评分条件和分值，按此自动评分</label><div><button className="primary small" disabled={busy||rules.criteria.some(c=>!c.description.trim())||(rules.criteria.length>0&&Math.abs(total-spec.max_points)>1e-6)} onClick={()=>void save()}>保存评分要求</button><button className="text-button" onClick={()=>setEditing(false)}>取消</button></div></div>}</details>;
}
