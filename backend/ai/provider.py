"""Only backend holds credentials. Never include raw provider errors or keys."""
import json
import asyncio
import os
import time
import re
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from . import cache

class ProviderError(ValueError): pass
ReasoningEffort=Literal['default','none','enabled','low','medium','high','xhigh','max']
class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    provider_name:str
    base_url:str
    model_id:str
    api_key:str = Field(repr=False)
    protocol:str='openai_chat_completions'
    timeout:int=60
    extra_body:dict=Field(default_factory=dict)
    reasoning_effort:ReasoningEffort='default'

def config_path():
    return Path(os.environ.get('MATHMASTER_AI_PROVIDER_FILE',str(Path.home()/'.config'/'mathmaster'/'provider.json')))
def read_path():
    path=config_path()
    legacy=Path.home()/'.config'/'math-408-agent'/'provider.json'
    return path if path.exists() or os.environ.get('MATHMASTER_AI_PROVIDER_FILE') else legacy

def load_legacy_profile():
    try:
        data=json.loads(read_path().read_text(encoding='utf-8')) if read_path().exists() else {'provider_name':os.environ.get('MATH408_PROVIDER_NAME','custom'),'base_url':os.environ.get('MATH408_BASE_URL',''),'model_id':os.environ.get('MATH408_MODEL_ID','')}
        data['api_key']=os.environ.get('MATHMASTER_AI_API_KEY') or os.environ.get('MATH408_API_KEY') or data.get('api_key','')
        profile=Profile.model_validate(data)
        if not profile.api_key: raise ProviderError('尚未配置本机 API 密钥。')
        validate_address(profile.base_url)
        return profile
    except ProviderError: raise
    except Exception: raise ProviderError('模型配置不存在或格式无效；请在本机设置。') from None

def validate_address(base):
    url=urlsplit(base)
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ProviderError('接口地址格式无效。')
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')):
        raise ProviderError('接口地址须使用 HTTPS；本机服务可使用 HTTP。')

def load_profile():
    from . import profiles
    if profiles.path().exists():return profiles.selected('chat')
    return load_legacy_profile()

def endpoint(profile,resource):
    base=profile.base_url.rstrip('/')
    for suffix in ('/chat/completions','/embeddings','/messages','/models'):
        if base.endswith(suffix):base=base[:-len(suffix)];break
    if profile.protocol=='anthropic_messages' and not base.endswith('/v1'):base+='/v1'
    return base+'/'+resource

def headers(profile):
    if profile.protocol=='anthropic_messages':return {'x-api-key':profile.api_key,'anthropic-version':'2023-06-01'}
    return {'Authorization':'Bearer '+profile.api_key}

def public_profile():
    try:
        p=load_profile()
        caps={}
        path=read_path().with_name('capabilities.json')
        try:
            observed=json.loads(path.read_text(encoding='utf-8'))
            if observed.get('model_id')==p.model_id and observed.get('base_url')==p.base_url:caps=observed
        except (OSError,ValueError):pass
        name='DeepSeek V4.1 Flash' if urlsplit(p.base_url).hostname=='api.deepseek.com' and p.model_id=='deepseek-flash' else p.model_id
        from . import reasoning
        return {'capabilities':caps,'configured':True,'provider_name':p.provider_name,'base_url':p.base_url,'model_id':p.model_id,'model_name':name,'protocol':p.protocol,**reasoning.describe(p)}
    except ProviderError: return {'configured':False}

def _payload(profile,messages,json_mode):
    from . import reasoning
    if profile.protocol=='anthropic_messages':
        system=[];converted=[]
        for m in messages:
            if m['role']=='system':system.append(m['content']);continue
            blocks=[]
            if isinstance(m['content'],str):blocks=[{'type':'text','text':m['content']}]
            else:
                for block in m['content']:
                    if block['type']=='text':blocks.append(block)
                    elif block['type']=='image_url':
                        url=block['image_url']['url']
                        match=re.fullmatch(r'data:(image/[a-zA-Z0-9.+-]+);base64,(.+)',url,re.S)
                        if not match:raise ProviderError('Anthropic 题图须为本地编码图片。')
                        blocks.append({'type':'image','source':{'type':'base64','media_type':match[1],'data':match[2]}})
            if converted and converted[-1]['role']==m['role']:converted[-1]['content'].extend(blocks)
            else:converted.append({'role':m['role'],'content':blocks})
        if json_mode:system.append('仅返回完整有效的 JSON 对象，不要使用 Markdown 代码块。')
        payload={'model':profile.model_id,'messages':converted,'system':'\n'.join(system),'max_tokens':2048,'temperature':0,'stream':False}
        payload.update(profile.extra_body)
        payload.pop('response_format',None)
        return reasoning.apply(profile,payload)
    if profile.protocol!='openai_chat_completions':raise ProviderError('当前配置不是聊天接口。')
    payload={'model':profile.model_id,'messages':messages,'max_tokens':2048,'temperature':0,'stream':False}
    payload.update(profile.extra_body)
    if json_mode:payload['response_format']={'type':'json_object'}
    return reasoning.apply(profile,payload)

def json_content(text):
    value=text.strip()
    if value.startswith('```'):
        value=re.sub(r'^```(?:json)?\s*|\s*```$','',value)
    return json.loads(value)

def _cacheable(result,json_mode,validator):
    if not isinstance(result.get('content'),str):return False
    if result.get('finish_reason') in ('length','content_filter'):return False
    try:
        if json_mode:
            value=json_content(result['content'])
            # A caller's validator can normalize compatible response envelopes.
            if not isinstance(value,dict) and validator is None:return False
        if validator:validator(result['content'])
        return True
    except (ValueError,KeyError,TypeError):return False

def request_profile(profile,messages,json_mode=True,cancelled=None,*,cache_kind='dialogue',use_cache=True,validator=None):
    started=time.perf_counter()
    payload=_payload(profile,messages,json_mode)
    # Only the hash is stored: no prompt, image payload, Authorization or API key.
    identity=cache.key({'version':1,'base_url':profile.base_url.rstrip('/'),'protocol':profile.protocol,
                        'credential_digest':cache.key(profile.api_key),'payload':payload})
    def cached_result(value):
        usage=value.get('usage',{})
        return {**value,'cache_hit':True,'cached_usage':usage,
                'avoided_prompt_tokens':cache.token_count(usage,'prompt_tokens'),
                'avoided_completion_tokens':cache.token_count(usage,'completion_tokens'),
                'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},
                'elapsed_ms':round((time.perf_counter()-started)*1000,2)}
    if not use_cache:
        result=_request_profile(profile,payload,cancelled)
        cache.record_remote(cache_kind,result['usage'])
        return {**result,'cache_hit':False}
    with cache.single_flight(cache_kind,identity,cancelled,ProviderError):
        value=cache.get(cache_kind,identity)
        if value is not None and _cacheable(value,json_mode,validator):return cached_result(value)
        generation=cache.generation()
        result=_request_profile(profile,payload,cancelled)
        cache.record_remote(cache_kind,result['usage'])
        if cancelled and cancelled():raise ProviderError('本轮模型请求已取消，输入保留。')
        if _cacheable(result,json_mode,validator):
            ttl=(30 if cache_kind in ('ocr','problem') else 7)*86400
            cache.put(cache_kind,identity,result,ttl,generation)
        return {**result,'cache_hit':False}

def _request_profile(profile,payload,cancelled):
    started=time.perf_counter()
    try:
        async def send():
            async with httpx.AsyncClient(timeout=profile.timeout) as client:
                task=asyncio.create_task(client.post(endpoint(profile,'messages' if profile.protocol=='anthropic_messages' else 'chat/completions'),
                    headers=headers(profile),json=payload))
                try:
                    while not task.done():
                        if cancelled and cancelled():
                            task.cancel()
                            raise ProviderError('本轮模型请求已取消，输入保留。')
                        await asyncio.sleep(.1)
                    return await task
                finally:
                    if not task.done():task.cancel()
        r=asyncio.run(send())
    except httpx.TimeoutException: raise ProviderError('模型请求超时，输入已保留，可重试。') from None
    except httpx.RequestError: raise ProviderError('模型网络连接失败，输入已保留，可重试。') from None
    if r.status_code!=200:
        reason={401:'鉴权失败',402:'额度不足',403:'调用被拒绝',404:'模型或接口不存在',429:'调用限流'}.get(r.status_code,'服务异常')
        raise ProviderError(f'{reason}（HTTP {r.status_code}），输入已保留。')
    try:
        data=r.json()
        if profile.protocol=='anthropic_messages':
            content=''.join(b['text'] for b in data['content'] if b.get('type')=='text')
            raw=data.get('usage',{});prompt=sum(raw.get(k,0) for k in ('input_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
            usage={'prompt_tokens':prompt,'completion_tokens':raw.get('output_tokens',0),'total_tokens':prompt+raw.get('output_tokens',0),'cached_tokens':raw.get('cache_read_input_tokens',0)}
            finish={'max_tokens':'length','end_turn':'stop'}.get(data.get('stop_reason'),data.get('stop_reason'))
        else:
            content=data['choices'][0]['message']['content'];usage=data.get('usage',{});finish=data['choices'][0].get('finish_reason')
        if not isinstance(content,str) or not content.strip():
            if finish=='length':raise ProviderError('思考或输出达到长度上限，未生成完整回复；请降低思考强度或在高级参数中增大 max_tokens。')
            raise ValueError()
    except ProviderError:raise
    except Exception: raise ProviderError('模型未返回可用文本。') from None
    return {'content':content,'model_id':data.get('model',profile.model_id),'finish_reason':finish,
            'elapsed_ms':round((time.perf_counter()-started)*1000,2),'usage':usage}
