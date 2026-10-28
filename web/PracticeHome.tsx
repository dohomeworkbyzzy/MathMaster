import {ArrowRight,BookOpen,CheckCircle2,Clock3,FileUp,Play,Plus,RotateCcw} from 'lucide-react';
import type {RecentQuestion} from './types';
import {RichText} from './math';
import './PracticeHome.css';

function practicedAt(stamp:string){return new Date(stamp).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'});}
export function PracticeHome({recent,loading,error,opening,stats,onOpen,onLibrary,onImport,onCreate,onRetry}:{
 recent:RecentQuestion[];loading:boolean;error:string;opening:boolean;
 stats:{questions:number;completed:number;wrong:number};onOpen:(id:string)=>void;
 onLibrary:()=>void;onImport:()=>void;onCreate:()=>void;onRetry:()=>void;
}){
 const last=recent[0];
 return <div className="practice-home">
  <div className="home-intro"><span className="home-eyebrow">你的练习，从这里接着写</span><p>题目、草稿和笔记都在，一起继续上次的思路。</p></div>
  {error&&<div className="home-error" role="alert"><span>暂时无法读取最近练习：{error}</span><button className="secondary small" onClick={onRetry}><RotateCcw size={14}/>重新读取</button></div>}
  {loading&&!last?<div className="home-loading" role="status">正在读取最近练习…</div>:last?<section className="resume-card" aria-label="上次练习">
   <div className="resume-copy"><div className="home-section-label"><Clock3 size={15}/>上次练习<span>{last.status||'尚未作答'}</span></div>
    <div className="resume-meta"><span className="subject-tag">{last.subject}</span><span>{last.paper_title||'自建题目'}</span></div>
    <h2>第 {last.number} 题</h2><div className="resume-preview"><RichText text={last.text||'图片题目，打开即可继续查看原题。'}/></div>
    <p className="resume-time">最近练习于 {practicedAt(last.last_practiced_at)}{!last.confirmed?' · 题目待核对':''}</p>
    <div className="resume-actions"><button className="primary" disabled={opening} onClick={()=>onOpen(last.id)}><Play size={16}/>{opening?'正在打开…':'继续上一道题'}<ArrowRight size={16}/></button><button className="secondary" onClick={onLibrary}>去题库选题<BookOpen size={15}/></button></div>
   </div><div className="resume-side">{last.images[0]?<img src={'/api/files/'+last.images[0]} alt="上次练习的题图预览"/>:<div className="resume-symbol" aria-hidden="true"><span>f(x)</span><i>∫</i><small>每一步，都算数。</small></div>}</div>
  </section>:!error&&<section className="resume-empty"><div className="resume-empty-icon"><BookOpen size={28}/></div><h2>{stats.questions?'开始你的下一道题':'从第一道题开始'}</h2><p>{stats.questions?'从题库选一道题开始，下次打开就能在这里继续。':'导入自己的试卷，或新建一道题。以后打开首页，就能一键接着做。'}</p><div className="resume-actions"><button className="primary" onClick={stats.questions?onLibrary:onImport}>{stats.questions?<BookOpen size={16}/>:<FileUp size={16}/>} {stats.questions?'去题库开始做题':'导入第一份试卷'}<ArrowRight size={16}/></button><button className="secondary" onClick={onCreate}><Plus size={16}/>新建题目</button></div></section>}
  <div className="home-summary"><span><BookOpen size={15}/><b>{stats.questions}</b> 道题目</span><span><CheckCircle2 size={15}/><b>{stats.completed}</b> 道已完成</span><span><RotateCcw size={15}/><b>{stats.wrong}</b> 道待复习</span></div>
  {recent.length>1&&<section className="home-recent" aria-label="最近练习"><div className="home-recent-heading"><h2>最近练习</h2><span>也可以从这里接着做</span></div><div className="home-recent-list">{recent.slice(1).map(q=><button className="recent-practice" key={q.id} disabled={opening} onClick={()=>onOpen(q.id)}><span className="recent-question-icon"><BookOpen size={18}/></span><div><div className="recent-practice-title"><b>第 {q.number} 题</b><span>{q.subject} · {q.paper_title||'自建题目'}</span></div><RichText text={q.text||'图片题目'}/></div><span className="recent-practice-state">{q.status||'尚未作答'}<small>{practicedAt(q.last_practiced_at)}</small></span><ArrowRight size={16}/></button>)}</div></section>}
  <div className="home-shortcuts"><button onClick={onLibrary}><BookOpen size={16}/>浏览题库<ArrowRight size={14}/></button><button onClick={onImport}><FileUp size={16}/>导入新试卷<ArrowRight size={14}/></button><button onClick={onCreate}><Plus size={16}/>创建新题目<ArrowRight size={14}/></button></div>
 </div>;
}
