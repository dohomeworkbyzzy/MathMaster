import { useEffect, useRef, useMemo } from 'react';
import katex from 'katex';
import { MathfieldElement } from 'mathlive';
import 'katex/dist/katex.min.css';
import 'mathlive/fonts.css';
// Bundled fonts eliminate MathLive's default CDN request. Disable audio and speech.
MathfieldElement.fontsDirectory='/mathlive/fonts';
MathfieldElement.soundsDirectory=null;
MathfieldElement.speechEngine='local';
MathfieldElement.speakHook=()=>{};
MathfieldElement.readAloudHook=()=>{};

export function Formula({latex,inline=false}:{latex:string;inline?:boolean}){
 const markup=useMemo(()=>katex.renderToString(latex,{displayMode:!inline,throwOnError:false,trust:false,strict:'ignore',maxExpand:300,output:'htmlAndMathml'}),[latex,inline]);
 return <span className={inline?'inline-formula':'formula'} dangerouslySetInnerHTML={{__html:markup}}/>;
}
export function RichText({text}:{text:string}){
 return <div className="rich-text">{text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g).map((part,i)=>part.startsWith('$$')?<Formula key={i} latex={part.slice(2,-2)}/>:part.startsWith('$')?<Formula key={i} latex={part.slice(1,-1)} inline/>:<span key={i}>{part}</span>)}</div>;
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
