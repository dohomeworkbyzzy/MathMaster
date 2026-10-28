export interface Step {step_id:string;rule:string;before_latex:string;after_latex:string;explanation_zh:string;children:Step[];verified:boolean;formula_latex?:string;choices_latex?:string;determinant_effect?:string;operation_type?:string;coefficient?:string;target_row?:number;source_row?:number}
export interface Result {operation:string;input_latex:string;result_latex:string;exact_result:string|null;approximate_result:string|null;method:string;assumptions:string[];steps:Step[];verified:boolean;warnings:string[];steps_complete:boolean;history_id:string;created_at:string;question_id:string|null;status?:string;action?:string}
export interface History {id:string;operation:string;question_id:string|null;request:Record<string,unknown>;result:Result;created_at:string}
export interface Attempt {updated_at?:string;answer:string;notes:string;draft:string;status:string;wrong:boolean}
export interface Question {id:string;paper_id:string|null;paper_title?:string;source_filename?:string;reference_filename?:string|null;reference_images?:string[];number:string;text:string;images:string[];subject:string;confirmed:boolean;reference_answer:string;answer?:string;notes?:string;draft?:string;status?:string;wrong?:boolean;attempt?:Attempt;calculations?:History[]}
export interface Paper {id:string;title:string;subject:string;filename:string;count:number;warnings:string[]}
export type RecentQuestion=Pick<Question,'id'|'paper_id'|'paper_title'|'number'|'text'|'images'|'subject'|'confirmed'> & {status:string|null;wrong:boolean|null;last_practiced_at:string};
// Freeze identity for this page, so another tab switching users cannot redirect
// an in-flight autosave. A user change saves first, then reloads the page.
const pageUser=localStorage.getItem('mathmaster-user-id')||'zzy';
export const userStorageKey=(key:string)=>pageUser==='zzy'?key:'mathmaster-user-'+pageUser+':'+key;
export async function api<T>(url:string,options?:RequestInit):Promise<T>{
 const headers=new Headers(options?.headers);headers.set('X-MathMaster-User',pageUser);
 if(!(options?.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
 const response=await fetch(url,{...options,headers});
 if(!response.ok){let message='请求失败';try{const error=await response.json();message=typeof error.detail==='string'?error.detail:JSON.stringify(error.detail);}catch{message=await response.text();}throw new Error(message);}
 return response.json();
}
export const json=(body:unknown,method='POST'):RequestInit=>({method,body:JSON.stringify(body)});
