import {useEffect,useRef,useState} from 'react';
import {Braces,ChevronDown,FileText,Monitor,PanelTop,Table2} from 'lucide-react';

export type Skin='original'|'code'|'word'|'sheet';
export const skins=[
 {id:'original',name:'原版',icon:Monitor},
 {id:'code',name:'VS Code',icon:Braces},
 {id:'word',name:'Word 文档',icon:FileText},
 {id:'sheet',name:'Excel 表格',icon:Table2},
] as const;
const filenames:Record<string,string>={home:'welcome.md',library:'resources.json',import:'import_data.py',wrong:'review.md',history:'output.log',practice:'workspace.py'};
const documentTitles:Record<Skin,string>={original:'MathMaster · 考研数学学习与计算工作台',code:'analysis.py - workspace - Visual Studio Code',word:'项目分析记录.docx - Word',sheet:'数据分析工作簿.xlsx - Excel'};
export function skinLabel(skin:Skin,view:string,fallback:string){return skin==='code'?(filenames[view]||'workspace.py'):skin==='word'?'项目分析记录':skin==='sheet'?'数据分析工作簿':fallback;}
export function useAppearance(){
 const [skin,setSkin]=useState<Skin>(()=>{try{const saved=localStorage.getItem('mathmaster-skin');return skins.some(item=>item.id===saved)?saved as Skin:'original';}catch{return 'original';}});
 const [covered,setCovered]=useState(false);
 const previousFocus=useRef<HTMLElement|null>(null);
 useEffect(()=>{try{localStorage.setItem('mathmaster-skin',skin);}catch{}document.documentElement.dataset.skin=skin;},[skin]);
 useEffect(()=>{document.title=covered?'项目进度周报.docx - Word':documentTitles[skin];document.documentElement.dataset.covered=String(covered);},[skin,covered]);
 useEffect(()=>()=>{delete document.documentElement.dataset.skin;delete document.documentElement.dataset.covered;document.title=documentTitles.original;},[]);
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='F8'&&!e.repeat&&!e.ctrlKey&&!e.altKey&&!e.metaKey){e.preventDefault();toggleCover();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[covered]);
 function toggleCover(){
  if(!covered){previousFocus.current=document.activeElement as HTMLElement;window.mathVirtualKeyboard?.hide();window.dispatchEvent(new Event('mathmaster-cover'));previousFocus.current?.blur();}
  setCovered(value=>!value);
 }
 useEffect(()=>{if(!covered&&previousFocus.current?.isConnected)previousFocus.current.focus({preventScroll:true});},[covered]);
 return {skin,setSkin,covered,toggleCover};
}

export function SkinPicker({skin,onChange,onCover}:{skin:Skin;onChange:(skin:Skin)=>void;onCover:()=>void}){
 const [open,setOpen]=useState(false);const host=useRef<HTMLDivElement>(null);const trigger=useRef<HTMLButtonElement>(null);
 const current=skins.find(item=>item.id===skin)!;const Icon=current.icon;
 useEffect(()=>{if(!open)return;const outside=(e:PointerEvent)=>{if(!host.current?.contains(e.target as Node))setOpen(false);};const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setOpen(false);trigger.current?.focus();}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);};},[open]);
 return <div className="skin-picker" ref={host}><button ref={trigger} className="skin-trigger" aria-label="切换皮肤" aria-expanded={open} onClick={()=>setOpen(!open)}><Icon size={15}/><span>{current.name}</span><ChevronDown size={12}/></button>{open&&<div className="skin-menu" aria-label="界面皮肤"><div className="skin-menu-heading">界面风格</div>{skins.map(item=>{const I=item.icon;return <button key={item.id} aria-pressed={skin===item.id} onClick={()=>{onChange(item.id);setOpen(false);trigger.current?.focus();}}><I size={17}/><span>{item.name}</span><span className="skin-selected">{skin===item.id?'✓':''}</span></button>;})}<div className="skin-menu-hint">选择会自动记住</div><button className="cover-menu-button" onClick={()=>{setOpen(false);onCover();}}><PanelTop size={16}/><span>切到工作报告</span><kbd>F8</kbd></button></div>}</div>;
}

// These spans are visual chrome; all working controls remain in the workspace.
export function OfficeRibbon({sheet=false}:{sheet?:boolean}){return <div className={'office-ribbon '+(sheet?'sheet-ribbon':'')} aria-hidden="true"><div className="ribbon-tabs"><span>文件</span><b>开始</b><span>插入</span><span>{sheet?'页面布局':'布局'}</span><span>{sheet?'公式':'引用'}</span><span>{sheet?'数据':'审阅'}</span><span>视图</span></div><div className="ribbon-tools"><div className="ribbon-clipboard"><FileText size={25}/><span>粘贴</span></div><div className="ribbon-group"><div className="ribbon-font"><span>{sheet?'等线':'宋体'}</span><span>11 <ChevronDown size={10}/></span></div><div className="ribbon-format"><b>B</b><i>I</i><u>U</u><span> A̲ </span><span>▤</span><span>≡</span></div><small>字体</small></div><div className="ribbon-group"><div className="ribbon-format">≡　☷　▤　↕</div><div className="ribbon-format">☰　▥　▦　⌄</div><small>{sheet?'对齐方式':'段落'}</small></div><div className="ribbon-styles"><div><b>AaBbCc</b><span>正文</span></div><div><b>AaBbCc</b><span>标题 1</span></div><small>{sheet?'单元格样式':'样式'}</small></div></div></div>;}
export function WorkspaceChrome({skin,view}:{skin:Skin;view:string}){
 if(skin==='original')return null;
 if(skin==='code')return <div className="code-chrome" aria-hidden="true"><div className="code-menubar"><Braces size={16}/><span>文件</span><span>编辑</span><span>选择</span><span>查看</span><span>运行</span><span>终端</span><span>帮助</span><span className="code-search">workspace</span></div><div className="code-filetab"><span><Braces size={14}/>{filenames[view]}<span>×</span></span><small>workspace / {filenames[view]}</small></div></div>;
 return <><OfficeRibbon sheet={skin==='sheet'}/>{skin==='sheet'?<div className="sheet-formula" aria-hidden="true"><span>A1</span><span>×　✓　<i>fx</i></span><b>数据分析工作簿</b></div>:<div className="document-ruler" aria-hidden="true"><span>1　·　2　·　3　·　4　·　5　·　6　·　7　·　8　·　9　·　10　·　11　·　12　·　13　·　14　·　15</span></div>}</>;
}
export function SkinStatus({skin}:{skin:Skin}){if(skin==='original')return null;return <footer className="skin-status" aria-hidden="true">{skin==='code'?<><span>⌘ main*　　✓ 0　 ⚠ 0</span><span>Ln 1, Col 1　　UTF-8　　Python</span></>:skin==='word'?<><span>第 1 页，共 1 页　　中文（中国）</span><span>打印布局　　100%　 ───●───</span></>:<><span>就绪　　<span className="sheet-tab">Sheet1</span>　＋</span><span>平均值: 0　　计数: 0　　100%</span></>}</footer>;}
export function WorkCover({onReturn}:{onReturn:()=>void}){
 const restore=useRef<HTMLButtonElement>(null);useEffect(()=>{restore.current?.focus();},[]);
 return <div className="work-cover" role="dialog" aria-modal="true" aria-label="工作报告"><div className="cover-titlebar"><FileText size={18}/><span>项目进度周报.docx — Word</span><button ref={restore} onClick={onReturn}>返回工作区 <kbd>F8</kbd></button></div><OfficeRibbon/><div className="cover-scroll"><article className="cover-paper"><div className="cover-kicker">PROJECT STATUS REPORT</div><h1>项目进度周报</h1><p className="cover-subtitle">工作进展与下一阶段计划</p><div className="cover-rule"/><h2>一、本周工作概况</h2><p>本周围绕项目交付计划开展需求梳理、数据核对与文档整理。各项任务按既定节奏推进，已完成阶段性材料汇总，并对待确认事项建立跟踪记录。</p><table><thead><tr><th>工作事项</th><th>当前进展</th><th>下一步安排</th></tr></thead><tbody><tr><td>需求与范围确认</td><td>已完成</td><td>更新需求清单</td></tr><tr><td>数据整理与核对</td><td>进行中</td><td>完成交叉检查</td></tr><tr><td>阶段成果评审</td><td>待安排</td><td>准备评审材料</td></tr></tbody></table><h2>二、重点事项</h2><p>持续跟进跨团队协作事项，统一文档版本与数据口径。对于影响进度的问题，及时记录处理方案及责任分工，确保交付材料完整、准确。</p><h2>三、下周工作计划</h2><ol><li>完成剩余数据核验，整理阶段性结果。</li><li>根据评审意见完善文档，确认交付清单。</li><li>跟踪关键节点，更新项目计划与问题记录。</li></ol><div className="cover-page-number">1</div></article></div><div className="cover-status"><span>第 1 页，共 1 页　　中文（中国）</span><span>100%</span></div></div>;
}
