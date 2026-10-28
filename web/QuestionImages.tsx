import {useCallback,useEffect,useRef,useState} from 'react';
import {AnnotationOverlay,type QuestionAnnotationController} from './QuestionAnnotations';

/** Stretch the complete image stack across the available width and height. */
export function QuestionImages({images,fit,preserveAspect=false,annotations}:{images:string[];fit:boolean;preserveAspect?:boolean;annotations?:QuestionAnnotationController}){
 const area=useRef<HTMLDivElement>(null);
 const elements=useRef<(HTMLImageElement|null)[]>([]);
 const [failed,setFailed]=useState<string[]>([]);
 const [layout,setLayout]=useState<{sizes:{width:number;height:number}[];gap:number}>({sizes:[],gap:6});
 const measure=useCallback(()=>{
  const container=area.current;if(!container||!fit)return;
  const originals=images.map((src,i)=>failed.includes(src)?{width:0,height:0}:{width:elements.current[i]?.naturalWidth||0,height:elements.current[i]?.naturalHeight||0});
  const gap=images.length>1?Math.min(6,container.clientHeight/(images.length*8)):0;
  const visible=originals.filter(size=>size.width>0&&size.height>0).length;
  const heightScale=Math.max(0,(container.clientHeight-gap*Math.max(0,visible-1))/Math.max(1,originals.reduce((total,size)=>total+size.height,0)));
  const widthScale=Math.min(...originals.filter(size=>size.width>0).map(size=>container.clientWidth/size.width));
  const scale=preserveAspect?Math.min(heightScale,widthScale):heightScale;
  const next={sizes:originals.map(size=>({width:size.width>0?(preserveAspect?size.width*scale:container.clientWidth):0,height:size.height*scale})),gap};
  setLayout(previous=>JSON.stringify(previous)===JSON.stringify(next)?previous:next);
 },[images,fit,failed,preserveAspect]);
 useEffect(()=>{
  const container=area.current;if(!container)return;
  const observer=new ResizeObserver(measure);observer.observe(container);measure();
  return()=>observer.disconnect();
 },[measure]);
 return <>{failed.some(src=>images.includes(src))&&<div className="question-image-errors" role="status">
  {failed.filter(src=>images.includes(src)).map(src=><a key={src} href={'/api/files/'+src} target="_blank" rel="noreferrer">题图加载失败，点击打开原图</a>)}
 </div>}<div className={'question-images'+(fit?' fitted-images':'')} ref={area} style={fit?{gap:layout.gap}:undefined}>
  {images.map((src,i)=><div className="question-image-frame" key={src} style={failed.includes(src)?{display:'none'}:fit?{width:layout.sizes[i]?.width||0,height:layout.sizes[i]?.height||0}:undefined}>
   <a href={'/api/files/'+src} target="_blank" rel="noreferrer" title="点击查看原始题图">
    <img ref={element=>{elements.current[i]=element;}} className="question-image" src={'/api/files/'+src}
     alt={`题目原始截图 ${i+1}`} onLoad={measure} onError={()=>{setFailed(previous=>previous.includes(src)?previous:[...previous,src]);measure();}}
     style={fit?{width:layout.sizes[i]?.width||0,height:layout.sizes[i]?.height||0}:undefined}/>
   </a>{annotations&&<AnnotationOverlay image={src} index={i} controller={annotations}/>}
  </div>)}
 </div></>;
}

/** Render solution sources only inside an explicitly opened answer view. */
export function ReferenceImages({images}:{images:string[]}){
 return <div className="reference-images">{images.map((src,i)=><a key={src} href={'/api/files/'+src} target="_blank" rel="noreferrer"><img src={'/api/files/'+src} alt={`原书参考解析 ${i+1}`} loading="lazy" style={{maxWidth:'100%',height:'auto',display:'block',margin:'8px auto'}}/></a>)}</div>;
}
