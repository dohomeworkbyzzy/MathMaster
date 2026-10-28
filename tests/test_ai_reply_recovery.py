import json
import pytest
from backend import db
from backend.ai import adaptive,cache,provider,service,knowledge


@pytest.fixture
def remote(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    db.init_db()
    profile=provider.Profile(provider_name='test',base_url='https://example.invalid/v1',model_id='deepseek-v4.1-flash-1017',api_key='private-test-key')
    monkeypatch.setattr(adaptive,'load_profile',lambda:profile)
    calls=[]
    replies=[]
    def request(p,payload,cancelled):
        calls.append(payload)
        value=replies.pop(0)
        if isinstance(value,Exception):raise value
        return {'content':value,'model_id':p.model_id,'finish_reason':'stop','elapsed_ms':10,
                'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
    monkeypatch.setattr(provider,'_request_profile',request)
    return calls,replies


def context():
    return {'question':{'id':'408-test','subject':'408','text':'计算机网络的逻辑组成是什么？'},'user_text':'我选d你看一下'}


@pytest.mark.parametrize('data',[
    {'message':'核对通信子网与资源子网。','calculation_requested':False,'computation_allowed':True},
    [{'message':'核对通信子网与资源子网。','current_text':'当前一步'}],
])
def test_real_deepseek_envelope_variants_preserve_reply_without_trusting_input_flags(data):
    reply=adaptive.parse_reply(json.dumps(data,ensure_ascii=False))
    assert reply.message=='核对通信子网与资源子网。'
    assert not {'calculation_requested','computation_allowed'}&reply.model_dump().keys()


@pytest.mark.parametrize('data',[
    [1],[],[{'message':'一'},{'message':'二'}],{},
    {'message':'继续','intent':'unknown'},
    {'message':'继续','action':'unknown'},
    {'tool_calls':[{'tool':'cs.subnet','input':{},'unexpected':True}]},
    {'message':'继续','observations':[{'skill_id':'408.network.prefix','quote':'d','judgement':'correct','reason':'test','unexpected':True}]},
])
def test_unusable_replies_and_nested_unknown_fields_are_still_rejected(data):
    with pytest.raises(ValueError):adaptive.parse_reply(json.dumps(data,ensure_ascii=False))


def test_bad_response_is_repaired_once_and_all_usage_is_counted(remote):
    calls,replies=remote
    replies.extend(['[1]','{"message":"通信子网负责传输与交换。","next_question":"资源子网负责什么？"}'])
    reply,meta=adaptive.model_reply(context())
    assert reply.message=='通信子网负责传输与交换。' and len(calls)==2
    assert meta['format_retries']==1 and meta['usage']['total_tokens']==240 and meta['elapsed_ms']==20
    assert calls[1]['messages'][-2]=={'role':'assistant','content':'[1]'}
    assert 'model_type' in calls[1]['messages'][-1]['content']
    assert cache.stats()['entries']==1  # The invalid first response is never cached.
    assert cache.stats()['totals']['remote_calls']==2


def test_compatible_reply_is_cacheable_using_the_same_parser(remote):
    calls,replies=remote
    replies.append('[{"message":"看当前选项。","calculation_requested":false}]')
    first,_=adaptive.model_reply(context())
    second,meta=adaptive.model_reply(context())
    assert first==second and len(calls)==1 and meta['cache_hit'] and meta['usage']['total_tokens']==0


def test_repeated_invalid_output_fails_without_saving_or_exposing_raw_reply(remote):
    calls,replies=remote
    replies.extend(['raw-private-response','{"intent":"unknown"}'])
    with pytest.raises(provider.ProviderError,match='自动修正一次') as exc:adaptive.model_reply(context())
    assert len(calls)==2 and cache.stats()['entries']==0
    assert 'raw-private-response' not in str(exc.value)


def test_network_failure_is_not_retried_as_a_format_error(remote):
    calls,replies=remote
    replies.append(provider.ProviderError('模型请求超时'))
    with pytest.raises(provider.ProviderError,match='超时'):adaptive.model_reply(context())
    assert len(calls)==1


def test_cancel_between_invalid_reply_and_repair_stops_the_second_request(remote):
    calls,replies=remote
    replies.append('[1]')
    with pytest.raises(provider.ProviderError,match='取消'):
        adaptive.model_reply(context(),cancelled=lambda:bool(calls))
    assert len(calls)==1


def test_408_prompt_contains_only_relevant_tools_and_retains_tutoring_constraints():
    prompt=adaptive.system_prompt('408')
    assert 'cs.subnet' in prompt and 'cs.cache_address' in prompt
    assert 'math.differentiate' not in prompt and 'math.series' not in prompt
    assert 'full_solution_allowed=false' in prompt and 'computation_allowed=false' in prompt
    assert 'math.differentiate' in adaptive.system_prompt()
    assert len(prompt)<len(adaptive.system_prompt())*.7


def test_408_skips_math_structure_extraction_but_keeps_stored_knowledge(monkeypatch):
    q={'id':'408-test','subject':'408','text':'题干','skills':[]}
    monkeypatch.setattr(knowledge,'prepared',lambda *a:None)
    monkeypatch.setattr(service,'request_profile',lambda *a,**k:pytest.fail('408 must not request math extraction'))
    prepared=service.prepare(q,None)
    assert prepared['prepared'] and prepared['kind']=='scratch' and prepared['config']=={}
    stored={**q,'knowledge_hit':True,'prepared':True}
    monkeypatch.setattr(knowledge,'prepared',lambda *a:stored)
    assert service.prepare(q,None)==stored


def test_408_choice_completion_does_not_make_an_optional_second_math_method_request(monkeypatch):
    q={'id':'408-test','subject':'408','kind':'scratch','skills':[],'reference_answer':'D'}
    calls=[]
    def model(*a):
        calls.append(1)
        return adaptive.Reply(intent='answer',action='complete',message='你选的D正确。',final_answer='D'),{'usage':{}}
    monkeypatch.setattr(adaptive,'model_reply',model)
    state,message,cards,meta=adaptive.run(q,adaptive.initial(q),'我选D',[],[])
    assert len(calls)==1 and state['stage']=='completed' and state['completion_check']=='valid'
    assert message=='你选的D正确。' and not cards
