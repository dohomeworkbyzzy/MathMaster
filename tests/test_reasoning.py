import copy,json
import httpx
import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.app import app
from backend.ai import provider as p,profiles,reasoning,cache,vectors

def profile(model='deepseek-flash',protocol='openai_chat_completions',effort='default',**kw):
    return p.Profile(provider_name='test',base_url='https://fixture.invalid/v1',model_id=model,api_key='PRIVATE_KEY',
                     protocol=protocol,reasoning_effort=effort,**kw)

@pytest.mark.parametrize('model,values',[('deepseek-flash',['default','none','low','high','max']),
    ('glm-5.3',['default','low','high','max']),('glm-5.3-flash',['default','low','high','max']),
    ('gpt-6.1-sol',['default','low','medium','high','xhigh','max'])])
def test_model_supported_levels_are_truthful(model,values):
    assert [o['value'] for o in reasoning.options(profile(model))]==values
    if model.startswith('glm-5.3'):
        with pytest.raises(ValueError):p._payload(profile(model,effort='none'),[],True)

def test_default_preserves_advanced_parameters_and_explicit_control_overrides_conflicts():
    extra={'thinking':{'type':'disabled'},'reasoning_effort':'low','max_tokens':12000,'temperature':.4}
    old=profile(extra_body=copy.deepcopy(extra))
    default=p._payload(old,[],True)
    assert all(default[k]==v for k,v in extra.items())
    high=p._payload(old.model_copy(update={'reasoning_effort':'high'}),[],True)
    assert high['thinking']=={'type':'enabled'} and high['reasoning_effort']=='high'
    assert high['max_tokens']==12000 and high['temperature']==.4 and old.extra_body==extra
    off=p._payload(old.model_copy(update={'reasoning_effort':'none'}),[],True)
    assert off['thinking']=={'type':'disabled'} and 'reasoning_effort' not in off

def test_anthropic_budget_adaptive_and_qwen_use_their_native_parameters():
    legacy=p._payload(profile('claude-sonnet-4-5','anthropic_messages','high'),[],True)
    assert legacy['thinking']=={'type':'enabled','budget_tokens':8192}
    assert legacy['max_tokens']>8192 and 'temperature' not in legacy
    adaptive=p._payload(profile('claude-opus-4-6','anthropic_messages','max'),[],True)
    assert adaptive['thinking']=={'type':'adaptive'} and adaptive['output_config']=={'effort':'max'}
    assert 'reasoning_effort' not in adaptive
    qwen=p._payload(profile('qwen3.8-max',effort='medium'),[],True)
    assert qwen['enable_thinking'] is True and qwen['thinking_budget']==4096
    with pytest.raises(ValueError):p._payload(profile('claude-sonnet-4-5','anthropic_messages','high',extra_body={'max_tokens':2048}),[],True)

def test_reasoning_changes_reach_the_wire_and_do_not_reuse_other_strength_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data');real=httpx.AsyncClient;calls=[]
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],'usage':{}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    p.request_profile(profile(effort='low'),[])
    p.request_profile(profile(effort='high'),[])
    assert p.request_profile(profile(effort='low'),[])['cache_hit']
    assert [call['reasoning_effort'] for call in calls]==['low','high']
    assert all(call['thinking']['type']=='enabled' for call in calls)

def test_gpt61_uses_native_completion_limit_and_omits_incompatible_sampling_parameters():
    value=profile('gpt-6.1-sol',effort='xhigh',extra_body={'max_tokens':24000,'top_p':.9,'logprobs':True})
    payload=p._payload(value,[],True)
    assert payload['reasoning_effort']=='xhigh' and payload['max_completion_tokens']==24000
    assert not {'temperature','top_p','top_logprobs','logprobs','max_tokens'}&payload.keys()
    assert p._payload(value.model_copy(update={'reasoning_effort':'default'}),[],True)['max_completion_tokens']==24000
    with pytest.raises(ValueError):p._payload(value.model_copy(update={'reasoning_effort':'none'}),[],True)

def test_quick_setting_persists_only_active_profile_and_preserves_keys_and_embedding_space(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data');monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE',str(tmp_path/'provider.json'))
    with TestClient(app) as client:
        body={'kind':'chat','provider_name':'GLM','base_url':'https://fixture.invalid/v1','model_id':'glm-5.3',
              'api_key':'PRIVATE_KEY','protocol':'openai_chat_completions','extra_body':{'max_tokens':8192}}
        saved=client.post('/api/ai/profiles',json=body).json();pid=saved['active_chat']
        current=client.get('/api/ai/provider').json();assert current['profile_id']==pid
        old=copy.deepcopy(profiles.read());space=vectors.space(profiles.selected('embedding'))
        reply=client.put('/api/ai/provider/reasoning',json={'profile_id':pid,'reasoning_effort':'low'})
        assert reply.status_code==200,reply.text
        assert reply.json()['reasoning_effort']=='low' and 'PRIVATE_KEY' not in reply.text
        after=profiles.read();assert after['active_embedding']==old['active_embedding']
        assert space==vectors.space(profiles.selected('embedding'))
        first=next(item for item in after['profiles'] if item['id']==pid)
        expected={**next(item for item in old['profiles'] if item['id']==pid),'reasoning_effort':'low'}
        assert first==expected and profiles.selected('chat').reasoning_effort=='low'
        assert client.put('/api/ai/provider/reasoning',json={'profile_id':pid,'reasoning_effort':'none'}).status_code==409
        other=client.post('/api/ai/profiles',json={**body,'provider_name':'Second'}).json()['profiles'][-1]['id']
        client.post('/api/ai/profiles/'+other+'/activate',json={})
        assert client.put('/api/ai/provider/reasoning',json={'profile_id':pid,'reasoning_effort':'high'}).status_code==409
        client.post('/api/ai/profiles/'+pid+'/activate',json={})
        assert client.get('/api/ai/provider').json()['reasoning_effort']=='low'
