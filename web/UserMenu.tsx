import {useEffect,useState} from 'react';
import {Users,X} from 'lucide-react';
import {api,json} from './types';

interface User {id:string;name:string}
interface Registry {users:User[];current_user:string;limit:number;remaining:number}

export function UserMenu({beforeChange}:{beforeChange:()=>Promise<unknown>}){
 const [registry,setRegistry]=useState<Registry|null>(null),[open,setOpen]=useState(false),[name,setName]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function refresh(){try{setRegistry(await api<Registry>('/api/users'));}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void refresh();},[]);
 const current=registry?.users.find(u=>u.id===registry.current_user)?.name||'zzy';
 async function change(id?:string){
  setBusy(true);setError('');
  try{
   await beforeChange();
   const result=await api<User>(id?'/api/users/'+encodeURIComponent(id)+'/select':'/api/users',json(id?{}:{name}));
   localStorage.setItem('mathmaster-user-id',result.id);
   location.reload();
  }catch(e){setError((e as Error).message);setBusy(false);void refresh();}
 }
 return <><button className="user-menu-trigger" aria-label={'选择用户，当前 '+current} onClick={()=>{setOpen(true);void refresh();}}><Users size={16}/><span>{current}</span></button>{open&&<div className="modal-backdrop"><section className="modal user-menu" role="dialog" aria-modal="true" aria-label="选择用户"><div className="modal-heading"><h3>选择用户</h3><button className="icon-button" aria-label="关闭用户选择" disabled={busy} onClick={()=>setOpen(false)}><X size={18}/></button></div><p>免密码 · 最多三个用户 · 分别保存模型选择和做题记录</p><div className="user-menu-list">{registry?.users.map(u=><button key={u.id} className={u.id===registry.current_user?'primary':'secondary'} disabled={busy} aria-label={'选择 '+u.name} onClick={()=>void change(u.id)}>{u.name}{u.id===registry.current_user?' · 当前用户':''}</button>)}</div>{registry&&registry.remaining>0?<form onSubmit={e=>{e.preventDefault();void change();}}><label>注册新用户<input aria-label="新用户名" value={name} maxLength={24} required disabled={busy} onChange={e=>setName(e.target.value)} placeholder="输入你的名字"/></label><button className="primary" disabled={busy||!name.trim()} type="submit">注册并进入</button><small>还可注册 {registry.remaining} 个用户</small></form>:<p>三个名额已满，可选择已有用户。</p>}{error&&<p className="ai-error" role="alert">{error}</p>}</section></div>}</>;
}
