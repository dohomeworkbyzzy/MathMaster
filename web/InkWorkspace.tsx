import {createContext,useContext,useLayoutEffect,useMemo,useRef,useState,type ReactNode,type RefObject} from 'react';
import {TouchpadInk,type InkController,type InkStroke} from './TouchpadInk';

type Binding={attach:(canvas:HTMLCanvasElement,toolbar:HTMLElement,onCommit:(strokes:InkStroke[])=>void)=>()=>void};
const InkContext=createContext<Binding|null>(null);

// The connection belongs to the app; individual questions only bind their paper.
export function InkWorkspace({children}:{children:ReactNode}){
 const canvas=useRef<HTMLCanvasElement|null>(null),controller=useRef<InkController|null>(null);
 const commit=useRef<(strokes:InkStroke[])=>void>(()=>{});
 const [toolbar,setToolbar]=useState<HTMLElement|null>(null);
 const binding=useMemo<Binding>(()=>({attach:(element,tools,onCommit)=>{
  controller.current?.suspend();canvas.current=element;commit.current=onCommit;setToolbar(tools);
  return()=>{controller.current?.suspend();canvas.current=null;commit.current=()=>{};setToolbar(null);};
 }}),[]);
 return <InkContext.Provider value={binding}>{children}<TouchpadInk canvas={canvas} controller={controller} toolbar={toolbar} onCommit={strokes=>commit.current(strokes)}/></InkContext.Provider>;
}

export function useInkPaper(canvas:RefObject<HTMLCanvasElement|null>,toolbar:RefObject<HTMLSpanElement|null>,onCommit:(strokes:InkStroke[])=>void){
 const binding=useContext(InkContext),handler=useRef(onCommit);handler.current=onCommit;
 useLayoutEffect(()=>{
  if(binding&&canvas.current&&toolbar.current)return binding.attach(canvas.current,toolbar.current,strokes=>handler.current(strokes));
 },[binding,canvas,toolbar]);
}
