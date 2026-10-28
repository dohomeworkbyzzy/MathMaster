import {useEffect,useRef,useState} from 'react';
import {api,json} from './types';

type Rating={level:number|null;label:string;reason:string;assessed:boolean;confidence?:string;source?:string;calculation_load?:string;fingerprint:string};
type Progress={level:number|null;label:string;goal_level:number|null;goal_label:string;successes:number;failures:number;reason:string};
type Info={rating:Rating;progress:Progress};
type Recommendation={question_id:string|null;number?:string;reason:string;difficulty?:Rating;target:Progress;current_difficulty:Rating;gap?:string|null};
type Preference='auto'|'easier'|'same'|'harder';

export function DifficultyPanel({qid,sid,version,busy,onOpen}:{qid:string;sid?:string;version?:number;busy:boolean;onOpen:(id:string)=>void}){
 const [info,setInfo]=useState<Info|null>(null),[result,setResult]=useState<Recommendation|null>(null);
 const [working,setWorking]=useState(false),[error,setError]=useState(''),[preference,setPreference]=useState<Preference>('auto');
 const generation=useRef(0),latestVersion=useRef(version);latestVersion.current=version;
 useEffect(()=>{
  const sequence=++generation.current;setInfo(null);setResult(null);setError('');setWorking(false);setPreference('auto');
  api<Info>('/api/questions/'+qid+'/difficulty').then(value=>{if(sequence===generation.current)setInfo(value);}).catch(e=>{if(sequence===generation.current)setError((e as Error).message);});
  return()=>{generation.current++;};
 },[qid]);
 useEffect(()=>{setResult(null);},[version]);
 async function run(action:()=>Promise<void>){setWorking(true);setError('');const sequence=generation.current;try{await action();}catch(e){if(sequence===generation.current)setError((e as Error).message);}finally{if(sequence===generation.current)setWorking(false);}}
 async function evaluate(){const sequence=generation.current;const value=await api<Info>('/api/questions/'+qid+'/difficulty/assess',json({}));if(sequence===generation.current){setInfo(value);setResult(null);}}
 async function correct(value:string){if(!info)return;const sequence=generation.current;const next=await api<Info>('/api/questions/'+qid+'/difficulty',json({level:value?Number(value):null,fingerprint:info.rating.fingerprint},'PUT'));if(sequence===generation.current){setInfo(next);setResult(null);}}
 async function recommend(){if(!sid)return;const sequence=generation.current,sentVersion=version;const next=await api<Recommendation>('/api/ai/sessions/'+sid+'/recommend',json({preference}));if(sequence===generation.current&&sentVersion===latestVersion.current){setResult(next);setInfo({rating:next.current_difficulty,progress:next.target});}}
 return <details className="difficulty-panel" open><summary>难度与下一题{info&&' · '+(info.rating.assessed?info.rating.label:'难度待确认')}</summary>
  {info&&<><div className="difficulty-heading"><b>本题：{info.rating.assessed?info.rating.label:'难度待确认'}</b>{info.rating.calculation_load&&<span>计算量：{{light:'少',medium:'中',heavy:'多'}[info.rating.calculation_load]}</span>}<span>{info.rating.source==='personal'?'个人校正':info.rating.confidence?({high:'较高可信度',medium:'中等可信度',low:'依据不足'}[info.rating.confidence]):''}</span></div><p>{info.rating.reason}</p>
   <div className="difficulty-tools"><button className="text-button" disabled={busy||working} onClick={()=>void run(evaluate)}>{working?'处理中…':info.rating.level?'重新评估难度':'评估本题难度'}</button><label>个人校正<select aria-label="个人校正题目难度" disabled={busy||working} value={info.rating.source==='personal'?String(info.rating.level):''} onChange={e=>void run(()=>correct(e.target.value))}><option value="">使用自动评级</option>{['入门','基础','标准','进阶','综合'].map((label,i)=><option key={label} value={i+1}>{i+1} · {label}</option>)}</select></label></div>
   {info.progress.level&&<p className="difficulty-progress">训练档位：{info.progress.label} · 独立通过 {info.progress.successes}/3{info.progress.goal_level&&info.progress.goal_level>info.progress.level&&' · 巩固后返回 '+info.progress.goal_label}</p>}</>}
  <div className="difficulty-options" role="group" aria-label="下一题难度">{([['auto','自动递进'],['easier','简单一点'],['same','保持难度'],['harder','挑战一下']] as const).map(([value,label])=><button key={value} className="secondary small" disabled={working||busy} aria-pressed={preference===value} onClick={()=>{setPreference(value);setResult(null);}}>{label}</button>)}</div>
  <button className="secondary small" disabled={!sid||busy||working} onClick={()=>void run(recommend)}>{working?'正在评估与选题…':'推荐下一题'}</button>
  {result&&<div className="difficulty-result" role="status"><p>{result.reason}</p>{result.question_id&&<button className="primary small" onClick={()=>onOpen(result.question_id!)}>开始推荐题{result.number?' · 第 '+result.number+' 题':''} →</button>}</div>}
  {error&&<p className="ai-error" role="alert">{error}</p>}
 </details>;
}
