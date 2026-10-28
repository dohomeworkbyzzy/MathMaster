import httpx
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field
from typing import Literal
from .schemas import Input
from . import profiles,vectors,provider
from .routes import call
from ..network_access import is_local_management

router=APIRouter()

class Setting(Input):
    id:str|None=Field(default=None,max_length=100)
    kind:Literal['chat','embedding']='chat'
    provider_name:str=Field(min_length=1,max_length=100)
    base_url:str=Field(max_length=1000)
    model_id:str=Field(min_length=1,max_length=200)
    api_key:str=Field(default='',max_length=4000,repr=False)
    protocol:Literal['openai_chat_completions','anthropic_messages','openai_embeddings']
    timeout:int=Field(default=60,ge=5,le=300)
    extra_body:dict=Field(default_factory=dict)
    reasoning_effort:provider.ReasoningEffort='default'

@router.get('/api/ai/profiles')
def list_profiles():return call(profiles.public)

@router.post('/api/ai/profiles')
def save(body:Setting):
    result=call(profiles.save,body.model_dump())
    if body.kind=='embedding' and body.id==result['active_embedding']:result['job_id']=call(vectors.enqueue)
    return result

@router.post('/api/ai/profiles/{pid}/activate')
def activate(pid:str,request:Request):
    item=call(profiles.get,pid);result=call(profiles.activate,pid)
    if item['kind']=='embedding':result['job_id']=call(vectors.enqueue)
    return result if is_local_management(request) else profiles.public_models(result)

@router.delete('/api/ai/profiles/{pid}')
def delete(pid:str):return call(profiles.delete,pid)

@router.post('/api/ai/profiles/{pid}/test')
def test(pid:str):
    item=call(profiles.get,pid);p=profiles.as_profile(item)
    if item['kind']=='embedding':
        values=call(vectors.embed,['泰勒展开与等价无穷小'],p)
        return {'ok':True,'dimensions':len(values[0])}
    result=call(lambda:provider.request_profile(p,[{'role':'user','content':'仅回复 JSON {"ok":true}'}],cache_kind='connection_test',use_cache=False))
    return {'ok':True,'model_id':result['model_id'],'elapsed_ms':result['elapsed_ms']}

@router.get('/api/ai/profiles/{pid}/models')
def models(pid:str):
    p=profiles.as_profile(call(profiles.get,pid))
    if p.protocol=='local_bge':return {'models':[p.model_id]}
    try:
        with httpx.Client(timeout=p.timeout) as client:r=client.get(provider.endpoint(p,'models'),headers=provider.headers(p))
    except httpx.RequestError:raise HTTPException(502,'获取模型列表失败，请检查网络。') from None
    if r.status_code!=200:raise HTTPException(502,f'此接口无法获取模型列表（HTTP {r.status_code}）；可以手动填写模型名称。')
    try:return {'models':[str(x['id']) for x in r.json()['data']][:500]}
    except (ValueError,KeyError,TypeError):raise HTTPException(502,'模型列表格式无效，请手动填写模型名称。') from None

@router.get('/api/ai/embeddings/status')
def status():return call(vectors.stats)

class Auto(Input):
    enabled:bool

@router.put('/api/ai/embeddings/auto')
def auto(body:Auto):
    result=call(profiles.auto,body.enabled)
    if body.enabled:result['job_id']=call(vectors.enqueue)
    return result

class Build(Input):
    paper_id:str|None=None

@router.post('/api/ai/embeddings/rebuild',status_code=202)
def rebuild(body:Build):return {'job_id':call(vectors.enqueue,body.paper_id)}

@router.get('/api/ai/similar')
def similar(text:str='',question_id:str|None=None,subject:str='',limit:int=8):
    if len(text)>2000 or not 1<=limit<=20:raise HTTPException(422,'检索文字最多 2000 字，结果数量为 1–20。')
    return call(vectors.search,text,question_id,subject,limit)
