import json
import os
from fastapi import APIRouter, HTTPException
from pydantic import Field
from typing import Literal
from . import service,cache,knowledge,difficulty
from .provider import Profile, ProviderError, config_path, load_profile, public_profile, request_profile,ReasoningEffort
from .schemas import Input
from .. import db

router=APIRouter()

def call(fn,*args):
    try:return fn(*args)
    except KeyError as exc:raise HTTPException(404,str(exc)) from None
    except ProviderError as exc:raise HTTPException(502,str(exc)) from None
    except ValueError as exc:raise HTTPException(409,str(exc)) from None

class Turn(Input):
    text:str=Field(min_length=1,max_length=6000)
    request_id:str=Field(min_length=1,max_length=80)
    version:int=Field(ge=0)

class Settings(Input):
    base_url:str=Field(max_length=1000)
    model_id:str=Field(min_length=1,max_length=200)
    api_key:str=Field(default='',max_length=4000,repr=False)

@router.get('/api/ai/provider')
def provider():
    from . import profiles
    result=public_profile()
    if result['configured']:result['profile_id']=profiles.read()['active_chat']
    return result

class ReasoningSetting(Input):
    reasoning_effort:ReasoningEffort='default'
    profile_id:str=Field(min_length=1,max_length=100)

@router.put('/api/ai/provider/reasoning')
def set_reasoning(body:ReasoningSetting):
    from . import profiles
    call(profiles.set_reasoning,body.reasoning_effort,body.profile_id)
    return provider()

@router.get('/api/ai/reasoning/options')
def reasoning_options(model_id:str='',protocol:str='openai_chat_completions'):
    from . import reasoning
    if len(model_id)>200 or protocol not in ('openai_chat_completions','anthropic_messages'):raise HTTPException(422,'模型或协议参数无效。')
    return reasoning.describe(Profile(provider_name='preview',base_url='',model_id=model_id,api_key='',protocol=protocol))

@router.put('/api/ai/provider')
def save_provider(body:Settings):
    if not body.base_url.startswith('https://'):raise HTTPException(422,'模型地址请填写 HTTPS 地址。')
    key=body.api_key.strip()
    if not key:
        try:key=load_profile().api_key
        except ProviderError:raise HTTPException(422,'请填写 API 密钥。') from None
    from . import profiles
    if profiles.path().exists():
        current=profiles.get(profiles.read()['active_chat']) if profiles.read()['active_chat'] else None
        call(profiles.save,{'id':current['id'] if current else None,'kind':'chat','provider_name':'custom','base_url':body.base_url,'model_id':body.model_id,'api_key':body.api_key,'protocol':'openai_chat_completions'})
        return public_profile()
    profile=Profile(provider_name='custom',base_url=body.base_url.rstrip('/'),model_id=body.model_id,api_key=key)
    path=config_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(profile.model_dump(),out,ensure_ascii=False)
    temporary.replace(path)
    return public_profile()

@router.post('/api/ai/provider/test')
def test_provider():
    result=call(lambda:request_profile(load_profile(),[{'role':'user','content':'仅回复JSON {"ok":true}'}],cache_kind='connection_test',use_cache=False))
    return {'ok':True,'model_id':result['model_id'],'elapsed_ms':result['elapsed_ms']}

@router.post('/api/questions/{qid}/ai')
def open_ai(qid:str):return call(service.open_session,qid)

@router.get('/api/ai/sessions/{sid}')
def get_ai(sid:str):return call(service.view,sid)

@router.post('/api/ai/sessions/{sid}/turns',status_code=202)
def send(sid:str,body:Turn):return call(service.submit,sid,body.text.strip(),body.request_id,body.version)

@router.post('/api/ai/sessions/{sid}/cancel')
def cancel(sid:str):return call(service.cancel,sid)

@router.post('/api/ai/sessions/{sid}/answer-exposed')
def exposed(sid:str):return call(service.exposed,sid)

@router.get('/api/ai/learning')
def learning():return service.learner_summary()

@router.get('/api/ai/cache')
def cache_stats():return {**cache.stats(),'knowledge':knowledge.stats()}

@router.delete('/api/ai/cache')
def clear_cache():return {**cache.clear(),'knowledge':knowledge.stats()}

@router.get('/api/ai/knowledge')
def knowledge_stats():return knowledge.stats()

class Recommendation(Input):
    preference:Literal['auto','easier','same','harder']='auto'

@router.post('/api/ai/sessions/{sid}/recommend')
def recommend(sid:str,body:Recommendation=Recommendation()):return call(service.recommend,sid,body.preference)

@router.get('/api/questions/{qid}/difficulty')
def difficulty_info(qid:str):return call(difficulty.info,qid)

@router.post('/api/questions/{qid}/difficulty/assess')
def assess_difficulty(qid:str):
    def assess():
        with db.connection() as c:q=knowledge.bank_question(c,qid)
        difficulty.assess([q],force=True)
        return difficulty.info(qid)
    return call(assess)

class DifficultyCorrection(Input):
    level:int|None=Field(default=None,ge=1,le=5,strict=True)
    fingerprint:str=Field(min_length=1,max_length=100)

@router.put('/api/questions/{qid}/difficulty')
def correct_difficulty(qid:str,body:DifficultyCorrection):
    call(difficulty.correct,qid,body.level,body.fingerprint)
    return call(difficulty.info,qid)


@router.post('/api/questions/{qid}/ai/transcribe')
def transcribe(qid:str):return call(service.transcribe,qid)

class Correction(Input):
    fingerprint:str=Field(max_length=100)
    text:str=Field(min_length=1,max_length=30000)

@router.put('/api/questions/{qid}/ai/transcription')
def confirm_transcription(qid:str,body:Correction):
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        q=knowledge.bank_question(con,qid)
        if service.fingerprint(q)!=body.fingerprint:raise HTTPException(409,'题干已更新，请重新核对题图。')
        con.execute('INSERT OR IGNORE INTO question_grading VALUES(?,?)',(qid,json.dumps(q['spec'],ensure_ascii=False)))
        con.execute('UPDATE questions SET text=?,confirmed=1 WHERE id=?',(body.text,qid))
        con.execute('UPDATE ai_observations SET excluded=1 WHERE question_id=?',(qid,))
    with db.connection() as con:new_q=knowledge.bank_question(con,qid)
    knowledge.promote(q,new_q,body.text)
    return {'ok':True}

@router.post('/api/ai/observations/{oid}/exclude')
def exclude(oid:str):
    with db.connection() as con:
        result=con.execute('UPDATE ai_observations SET excluded=1 WHERE id=?',(oid,))
        if not result.rowcount:raise HTTPException(404,'观察记录不存在。')
    return {'ok':True}
