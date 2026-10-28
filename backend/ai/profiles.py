"""Local provider switchboard. API keys are never returned to the browser."""
import json
import os
import threading
import uuid
from urllib.parse import urlsplit
from . import provider
from .. import users

LOCK=threading.RLock()
LOCAL={'id':'builtin-bge','kind':'embedding','provider_name':'内置中文向量（免费）','base_url':'','model_id':'bge-small-zh-v1.5','api_key':'','protocol':'local_bge','timeout':60,'extra_body':{}}

def path():return provider.config_path().with_name('providers.json')

def _read():
    if path().exists():
        try:return json.loads(path().read_text(encoding='utf-8'))
        except (ValueError,OSError):raise provider.ProviderError('API 配置库无法读取，请检查本机配置文件。') from None
    entries=[dict(LOCAL)];chat=None
    try:
        old=provider.load_legacy_profile()
        entries.append({'id':'legacy-chat','kind':'chat',**old.model_dump()});chat='legacy-chat'
    except provider.ProviderError:pass
    return {'version':1,'profiles':entries,'active_chat':chat,'active_embedding':LOCAL['id'],'auto_index':True}

def read():
    value=_read();prefs=users.preferences()
    for kind in ('chat','embedding'):
        selected=prefs.get('active_'+kind)
        if any(p['id']==selected and p['kind']==kind for p in value['profiles']):value['active_'+kind]=selected
    for p in value['profiles']:
        effort=prefs.get('reasoning',{}).get(p['id'])
        if effort is not None:p['reasoning_effort']=effort
    return value

def write(value):
    target=path();target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)

def initialize():
    with LOCK:
        if not path().exists():write(read())

def public():
    with LOCK:value=read()
    from . import reasoning
    return {**value,'profiles':[{k:v for k,v in p.items() if k!='api_key'}|{'has_api_key':bool(p['api_key']),**reasoning.describe(as_profile(p))} for p in value['profiles']]}

def public_models(value=None):
    value = read() if value is None else value
    return {'read_only': True, 'can_activate': True,
            'active_chat': value.get('active_chat'), 'active_embedding': value.get('active_embedding'),
            'profiles': [{k: p[k] for k in ('id', 'kind', 'model_id')} for p in value['profiles']]}

def selected(kind):
    with LOCK:value=read()
    item=next((p for p in value['profiles'] if p['id']==value['active_'+kind] and p['kind']==kind),None)
    if not item:raise provider.ProviderError('尚未选择'+('聊天' if kind=='chat' else '向量')+'配置。')
    result=provider.Profile.model_validate({k:v for k,v in item.items() if k not in ('id','kind')})
    if result.protocol!='local_bge':
        provider.validate_address(result.base_url)
        if not result.api_key:raise provider.ProviderError('当前 API 配置没有密钥。')
    return result

def get(pid):
    with LOCK:value=read()
    item=next((p for p in value['profiles'] if p['id']==pid),None)
    if not item:raise KeyError('API 配置不存在。')
    return item

def save(body):
    with LOCK:
        value=_read();pid=body.get('id') or uuid.uuid4().hex
        old=next((p for p in value['profiles'] if p['id']==pid),None)
        if pid==LOCAL['id']:raise ValueError('内置向量配置不能修改。')
        kind=body['kind'];protocol=body['protocol']
        allowed=('openai_chat_completions','anthropic_messages') if kind=='chat' else ('openai_embeddings',)
        if kind not in ('chat','embedding') or protocol not in allowed:raise ValueError('该用途不支持所选协议。')
        if old and old['kind']!=kind:raise ValueError('不能修改配置用途，请新增配置。')
        provider.validate_address(body['base_url'])
        key=body.get('api_key','').strip()
        if not key and old:
            if urlsplit(old['base_url']).hostname!=urlsplit(body['base_url']).hostname:
                raise ValueError('接口主机已改变，请重新填写密钥。')
            key=old['api_key']
        if not key:raise ValueError('请填写 API 密钥。')
        if any(key in body.get('extra_body',{}) for key in ('model','messages','system','stream','input','encoding_format','api_key','authorization','x-api-key')):
            raise ValueError('高级参数不能覆盖模型、消息或向量输入。')
        p=provider.Profile(provider_name=body['provider_name'],base_url=body['base_url'].rstrip('/'),model_id=body['model_id'].strip(),
                           api_key=key,protocol=protocol,timeout=body.get('timeout',60),extra_body=body.get('extra_body',{}),reasoning_effort=body.get('reasoning_effort','default'))
        if not p.model_id or not p.provider_name:raise ValueError('请填写配置名称和模型名称。')
        if kind=='embedding' and p.reasoning_effort!='default':raise ValueError('向量模型不使用思考强度。')
        if kind=='chat':provider._payload(p,[{'role':'user','content':'JSON'}],True)
        entry={'id':pid,'kind':kind,**p.model_dump()}
        value['profiles']=[entry if i['id']==pid else i for i in value['profiles']]
        if not old:value['profiles'].append(entry)
        if not value['active_'+kind]:value['active_'+kind]=pid
        write(value)
    return public()

def activate(pid):
    with LOCK:
        item=get(pid)
        if not users.save_preferences(**{'active_'+item['kind']:pid}):
            value=read();value['active_'+item['kind']]=pid;write(value)
    return public()

def delete(pid):
    with LOCK:
        value=read();item=get(pid)
        if pid==LOCAL['id'] or value['active_'+item['kind']]==pid:raise ValueError('请先切换到其他配置，再删除。')
        value['profiles']=[p for p in value['profiles'] if p['id']!=pid];write(value)
    return public()

def auto(enabled):
    with LOCK:value=_read();value['auto_index']=enabled;write(value)
    return public()

def as_profile(item):return provider.Profile.model_validate({k:v for k,v in item.items() if k not in ('id','kind')})

def set_reasoning(effort,expected_profile_id):
    with LOCK:
        value=read();pid=value['active_chat']
        if pid!=expected_profile_id:raise ValueError('当前解题 API 已切换，请刷新后再设置思考强度。')
        item=get(pid);p=as_profile({**item,'reasoning_effort':effort})
        provider._payload(p,[{'role':'user','content':'JSON'}],True)
        reasoning={**users.preferences().get('reasoning',{}),pid:p.reasoning_effort}
        if not users.save_preferences(reasoning=reasoning):
            entry={**item,'reasoning_effort':p.reasoning_effort}
            value['profiles']=[entry if i['id']==pid else i for i in value['profiles']];write(value)
    return provider.public_profile()
