import { useEffect, useRef, useMemo, type ReactNode } from 'react';
import katex from 'katex';
import { MathfieldElement } from 'mathlive';
import 'katex/dist/katex.min.css';
import 'mathlive/fonts.css';
import './richText.css';
// Bundled fonts eliminate MathLive's default CDN request. Disable audio and speech.
MathfieldElement.fontsDirectory='/mathlive/fonts';
MathfieldElement.soundsDirectory=null;
MathfieldElement.speechEngine='local';
MathfieldElement.speakHook=()=>{};
MathfieldElement.readAloudHook=()=>{};

export function Formula({latex,inline=false}:{latex:string;inline?:boolean}){
 const markup=useMemo(()=>katex.renderToString(latex,{displayMode:!inline,throwOnError:false,trust:false,strict:'ignore',maxExpand:300,output:'htmlAndMathml'}),[latex,inline]);
 return <span className={inline?'inline-formula':'formula'} tabIndex={inline?undefined:0} dangerouslySetInnerHTML={{__html:markup}}/>;
}
export function RichText({text}:{text:string}){
 const blocks=useMemo(()=>{
  const result:ReactNode[]=[];let paragraph:ReactNode[]=[];
  function flush(){
   if(typeof paragraph[0]==='string')paragraph[0]=paragraph[0].trimStart();
   const last=paragraph.length-1;if(typeof paragraph[last]==='string')paragraph[last]=paragraph[last].trimEnd();
   if(paragraph.some(part=>typeof part!=='string'||part.trim()))result.push(<p className="rich-paragraph" key={result.length}>{paragraph}</p>);
   paragraph=[];
  }
  const parts=text.split(/(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g);
  for(const [i,part] of parts.entries()){
   const display=i%2===1&&(part.startsWith('\\[')||part.startsWith('$$'));
   const inline=i%2===1&&!display;
   if(display){flush();result.push(<Formula key={result.length} latex={part.slice(2,-2).trim()}/>);}
   else if(inline)paragraph.push(<Formula key={'math-'+i} latex={part.startsWith('\\(')?part.slice(2,-2):part.slice(1,-1)} inline/>);
   else for(const [j,line] of part.split(/\n[ \t]*\n+/).entries()){if(j)flush();paragraph.push(line);}
  }
  flush();return result;
 },[text]);
 return <div className="rich-text">{blocks}</div>;
}
export function MathInput({value,onChange,fieldRef}:{value:string;onChange:(s:string)=>void;fieldRef?:React.RefObject<MathfieldElement|null>}){
 const container=useRef<HTMLDivElement>(null);const mf=useRef<MathfieldElement|null>(null);
 const change=useRef(onChange);change.current=onChange;
 useEffect(()=>{
  const el=new MathfieldElement();el.mathVirtualKeyboardPolicy='manual';el.setAttribute('aria-label','数学公式输入');el.value=value;
  el.addEventListener('input',()=>change.current(el.value));container.current?.appendChild(el);mf.current=el;if(fieldRef)fieldRef.current=el;
  return()=>{el.remove();mf.current=null;if(fieldRef)fieldRef.current=null;};
 },[]);
 useEffect(()=>{if(mf.current&&mf.current.value!==value)mf.current.setValue(value,{silenceNotifications:true});},[value]);
 return <div className="math-input" ref={container}/>;
}
