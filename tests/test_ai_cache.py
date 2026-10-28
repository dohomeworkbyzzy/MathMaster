import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend import db
from backend.ai import cache,provider,jobs
from backend.ai.context import messages,history_memory,compact_schema,tool_card
from backend.ai.adaptive import Reply,system_prompt
from backend.ai.service import transcribe,open_session,prepare
from PIL import Image

@pytest.fixture(autouse=True)
def isolated_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    db.init_db()

def profile(**changes):
    return provider.Profile(provider_name='fixture',base_url='https://example.invalid/v1',model_id='fixture-model',api_key='fixture-private-key',**changes)

def response(content='{"message":"这一轮","next_question":"下一步？"}'):
    return {'content':content,'model_id':'fixture-model','usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':80},'finish_reason':'stop','elapsed_ms':10}

def test_exact_request_survives_restart_accounts_zero_new_tokens_and_keeps_secrets_out(monkeypatch):
    calls=[]
    monkeypatch.setattr(provider,'_request_profile',lambda *a:(calls.append(a[1]) or response()))
    p=profile();request=[{'role':'user','content':'不要把我的原始请求存入缓存！'}]
    first=provider.request_profile(p,request)
    second=provider.request_profile(p,copy.deepcopy(request))
    assert len(calls)==1 and not first['cache_hit'] and second['cache_hit']
    assert second['usage']['total_tokens']==0 and second['cached_usage']['total_tokens']==120
    assert second['avoided_prompt_tokens']==100
    # Re-open every connection, then read the persisted content without an in-memory cache.
    assert cache.path().is_file()
    stats=cache.stats()['totals']
    assert stats['remote_calls']==1 and stats['hits']==1
    assert stats['prompt_tokens']==100 and stats['avoided_prompt_tokens']==100
    assert stats['provider_cached_tokens']==80
    with cache.connection() as con:
        stored=json.dumps([dict(r) for r in con.execute('SELECT * FROM entries')],ensure_ascii=False)
    assert 'fixture-private-key' not in stored
    assert request[0]['content'] not in stored

def test_model_account_prompt_and_state_changes_cannot_reuse_old_reply(monkeypatch):
    calls=[]
    monkeypatch.setattr(provider,'_request_profile',lambda *a:(calls.append(1) or response()))
    p=profile()
    cases=[(p,'x'),(p.model_copy(update={'model_id':'other'}),'x'),
           (p.model_copy(update={'api_key':'other-account'}),'x'),
           (p.model_copy(update={'base_url':'https://other.invalid/v1'}),'x'),
           (p,'x changed'),(p.model_copy(update={'extra_body':{'temperature':.2}}),'x')]
    for model,text in cases:assert not provider.request_profile(model,[{'role':'user','content':text}])['cache_hit']
    assert len(calls)==6

def test_concurrent_identical_request_only_calls_provider_once(monkeypatch):
    entered=threading.Event();release=threading.Event();calls=[]
    def remote(*a):
        calls.append(1);entered.set();assert release.wait(5);return response()
    monkeypatch.setattr(provider,'_request_profile',remote)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(provider.request_profile,profile(),[{'role':'user','content':'same'}])
        assert entered.wait(3)
        second=pool.submit(provider.request_profile,profile(),[{'role':'user','content':'same'}])
        release.set()
        values=[first.result(),second.result()]
    assert len(calls)==1 and sum(r['cache_hit'] for r in values)==1

@pytest.mark.parametrize('content',['invalid JSON','{"intent":"nonexistent"}'])
def test_invalid_model_replies_are_not_cached(monkeypatch,content):
    calls=[]
    monkeypatch.setattr(provider,'_request_profile',lambda *a:(calls.append(1) or response(content)))
    for _ in range(2):provider.request_profile(profile(),[{'role':'user','content':'same'}],validator=lambda text:Reply.model_validate(provider.json_content(text)))
    assert len(calls)==2 and cache.stats()['entries']==0

def test_network_failure_and_cancel_do_not_populate_cache(monkeypatch):
    def fail(*a):raise provider.ProviderError('network failure')
    monkeypatch.setattr(provider,'_request_profile',fail)
    with pytest.raises(provider.ProviderError):provider.request_profile(profile(),[],cancelled=lambda:False)
    with pytest.raises(provider.ProviderError):provider.request_profile(profile(),[],cancelled=lambda:True)
    assert cache.stats()['entries']==0

def test_clear_during_request_cannot_repopulate_removed_generation(monkeypatch):
    def clear_while_running(*a):cache.clear();return response()
    monkeypatch.setattr(provider,'_request_profile',clear_while_running)
    provider.request_profile(profile(),[])
    assert cache.stats()['entries']==0

def test_expiry_and_lru_limits(monkeypatch):
    generation=cache.generation()
    cache.put('fixture','expired',{'a':1},-1,generation)
    assert cache.get('fixture','expired') is None
    monkeypatch.setattr(cache,'MAX_ENTRIES',2)
    for i in range(3):cache.put('fixture',str(i),{'value':i},60,generation)
    assert cache.stats()['entries']==2
    assert cache.get('fixture','0') is None
    assert cache.get('fixture','2')['value']==2

def test_compute_reuse_validates_input_keeps_order_and_does_not_cache_errors(monkeypatch):
    calls=[]
    def compute(*a):calls.append(a);return {'exact_result':'x**2/2 + O(x**3)','remainder':'O(x**3)'}
    monkeypatch.setattr(jobs,'_run_job',compute)
    args={'expression':'exp(x)-1-x','through_degree':2}
    assert not jobs.run_job('math.series',args)['cache_hit']
    assert jobs.run_job('math.series',args)['cache_hit']
    assert len(calls)==1
    jobs.run_job('math.series',{**args,'through_degree':3});assert len(calls)==2
    with pytest.raises(jobs.JobError):jobs.run_job('math.series',{**args,'unexpected':'bad'})
    with pytest.raises(jobs.JobError):jobs.run_job('math.series',args,cancelled=lambda:True)

def test_question_image_content_cache_changes_with_crop_and_preserves_bank(monkeypatch):
    from backend.ai import service
    calls=[]
    monkeypatch.setattr(service,'load_profile',profile)
    monkeypatch.setattr(provider,'_request_profile',lambda *a:(calls.append(1) or response('{"text":"求 sin(x)/x 在0的极限","uncertain":false}')))
    name='fixture/Q01.png';image=db.DATA/'uploads'/name;image.parent.mkdir(parents=True)
    Image.new('RGB',(30,30),'white').save(image)
    with db.connection() as con:
        con.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',('q',None,'1','原图未核对',json.dumps([name]),'','数学二',0,'now'))
    first=transcribe('q');second=transcribe('q')
    assert not first['cache_hit'] and second['cache_hit'] and len(calls)==1
    with db.connection() as con:assert con.execute('SELECT text FROM questions').fetchone()[0]=='原图未核对'
    Image.new('RGB',(30,30),'black').save(image)
    assert not transcribe('q')['cache_hit'] and len(calls)==2

def test_tool_context_has_no_duplicate_saved_results_and_keeps_remainder_conditions():
    original={'number':1,'tool':'math.series','input':{'expression':'sin(x)','through_degree':3},
              'result':{'exact_result':'x-x**3/6+O(x**5)','remainder':'O(x**5)','assumptions':['x is real'],
                        'warnings':['仅渐近等价'],'steps':[{'rule':'series','explanation_zh':'local step'}]*200},
              'saved_result':{'steps':['long result']*200},'history_id':'private-history-id','valid':True}
    compact=tool_card(original)
    assert 'saved_result' not in compact and 'history_id' not in compact
    assert compact['result']['remainder']=='O(x**5)' and compact['result']['assumptions']==['x is real']
    assert len(json.dumps(compact))<len(json.dumps(original))/5
    base={'question':{'id':'q','text':'sin(x)/x','config':{},'revision':'original-image-revision'},'state':{'branch':1},'workspace':[original],'user_text':'第一步'}
    changed={**base,'user_text':'第二步','state':{'branch':2}}
    a,b=messages(system_prompt(),base),messages(system_prompt(),changed)
    assert a[:2]==b[:2] and a[2]!=b[2]
    revised=copy.deepcopy(base);revised['question']['revision']='new-image-revision'
    assert messages(system_prompt(),revised)[1]!=a[1]
    assert json.loads(a[2]['content'])['user_text']=='第一步'
    assert original['result']['steps'] # Compaction must not edit actual history.

def test_full_history_is_retained_locally_when_working_memory_is_bounded():
    history=[{'user':'user-'+str(i),'assistant':'teacher-'+str(i)} for i in range(30)]
    before=copy.deepcopy(history);memory=history_memory(history)
    assert history==before and memory['earlier_turn_count']==24
    assert len(memory['earlier_excerpts'])==8 and memory['excerpts_are_incomplete']

def test_connection_test_always_uses_network(monkeypatch):
    calls=[]
    monkeypatch.setattr(provider,'_request_profile',lambda *a:(calls.append(1) or response('{"ok":true}')))
    for _ in range(2):provider.request_profile(profile(),[],use_cache=False,cache_kind='connection_test')
    assert len(calls)==2 and cache.stats()['entries']==0
