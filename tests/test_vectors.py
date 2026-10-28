import json
import sqlite3
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from backend import db,grading
from backend.ai import knowledge as k,vectors as v,profiles as ps,provider as p,service

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE',str(tmp_path/'config/provider.json'))
    monkeypatch.setenv('MATHMASTER_EMBEDDING_MODEL_DIR',str(tmp_path/'missing-weights'))
    db.init_db();grading.init();k.init();v.init()
    v._stop.clear()
    yield
    v.stop()

def q(qid,topic='等价无穷小',subject='数学二',text='完全相同的题目参数 12345',secret='SECRET_SOLUTION'):
    with db.connection() as c:
        c.execute('INSERT INTO questions VALUES(?,NULL,?,?,?, ?,?,1,?)',(qid,'1',text,'[]','SECRET_ANSWER',subject,k.now()))
        value=k.bank_question(c,qid)
    payload={'question_id':qid,'question_text':text,'uncertain':False,'has_diagram':False,'topic':topic,'problem':{},
             'methods':[{'name':'泰勒展开' if '无穷小' in topic else '条件分析','first_question':'用哪个方法？','checkpoints':['确认适用条件']}],
             'private_solution':secret,'rubric':'SECRET_RUBRIC'}
    k.put(value,payload,'fixture')
    return value

def encoder(texts,profile=None,query=False,cancelled=None):
    return [[1.,0.,0.] if '无穷小' in s else [0.,1.,0.] if 'Cache' in s else [0.,0.,1.] for s in texts]

def remote(**updates):
    return p.Profile(provider_name='test',base_url='https://fixture.invalid/v1',model_id='embed-a',api_key='SECRET_KEY',protocol='openai_embeddings').model_copy(update=updates)

def test_knowledge_direction_over_identical_stem_no_private_answer_and_vector_reuse(monkeypatch):
    qs=[q('a'),q('b'),q('c','矩阵的秩')];calls=[]
    monkeypatch.setattr(v,'embed',lambda *a,**kw:(calls.append(1) or encoder(*a,**kw)))
    v.index_questions(qs);assert len(calls)==1
    v.index_questions(qs);assert len(calls)==1
    result=v.search(qid='a');assert result['items'][0]['question_id']=='b'
    assert result['items'][0]['score']>result['items'][1]['score']
    with db.connection() as c:
        docs=''.join(r[0] for r in c.execute('SELECT document FROM question_embeddings'))
        assert all(secret not in docs for secret in ('SECRET_SOLUTION','SECRET_RUBRIC','SECRET_ANSWER','12345'))
    assert 'SECRET' not in json.dumps(result)

def test_changed_questions_are_excluded_and_embedding_model_spaces_do_not_mix(monkeypatch):
    qs=[q('a'),q('b')];monkeypatch.setattr(v,'embed',encoder);v.index_questions(qs)
    with db.connection() as c:c.execute("UPDATE questions SET text='changed' WHERE id='b'")
    assert v.search(qid='a')['items']==[]
    monkeypatch.setattr(ps,'selected',lambda kind:remote(model_id='different'))
    assert v.search('等价无穷小')['items']==[]
    assert v.stats()['indexed']==0

def test_408_specific_concepts_only_without_encoding_incidental_options():
    value=q('c','组成原理 · Cache',subject='408',text='组相联 Cache 的标记位、组号与块内地址如何划分？\nA. SECRET_CHOICE 12345')
    d=v.document(value,k.get(value))
    assert '地址划分' in d['text'] and '缓存映射方式' in d['text']
    assert 'SECRET_CHOICE' not in d['text'] and '12345' not in d['text']

def test_remote_embedding_index_order_cache_account_isolation_and_invalid_outputs(monkeypatch):
    real=httpx.AsyncClient;calls=[]
    def handle(request):
        body=json.loads(request.content);calls.append((str(request.url),body))
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[float(i+1),1.]} for i in reversed(range(len(body['input'])))],'usage':{'prompt_tokens':20,'total_tokens':20}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    first=v.embed(['a','b'],remote());assert len(first)==2 and first[0][0]<first[1][0]
    cached=v.embed(['a','b'],remote())
    assert all(a==pytest.approx(b) for a,b in zip(cached,first)) and len(calls)==1
    v.embed(['a','b'],remote(api_key='other'));assert len(calls)==2
    assert calls[0][0]=='https://fixture.invalid/v1/embeddings'
    def invalid(request):return httpx.Response(200,json={'data':[{'index':0,'embedding':[0.,0.]},{'index':0,'embedding':[1.,1.]}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(invalid),**kw))
    with pytest.raises(p.ProviderError):v.embed(['invalid-a','invalid-b'],remote())

def test_anthropic_messages_headers_images_system_usage_and_endpoint(monkeypatch):
    profile=remote(protocol='anthropic_messages',base_url='https://anthropic.invalid')
    messages=[{'role':'system','content':'引导解题'}, {'role':'user','content':[{'type':'text','text':'识别题图'},{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]}]
    payload=p._payload(profile,messages,True)
    assert '引导解题' in payload['system'] and 'response_format' not in payload
    assert payload['messages'][0]['content'][1]['source']=={'type':'base64','media_type':'image/png','data':'YQ=='}
    real=httpx.AsyncClient
    def handle(request):
        assert str(request.url)=='https://anthropic.invalid/v1/messages'
        assert request.headers['x-api-key']=='SECRET_KEY' and request.headers['anthropic-version']=='2023-06-01'
        assert 'authorization' not in request.headers
        return httpx.Response(200,json={'content':[{'type':'thinking','thinking':'hidden'},{'type':'text','text':'{"ok":true}'}],'stop_reason':'max_tokens',
          'usage':{'input_tokens':10,'cache_read_input_tokens':20,'cache_creation_input_tokens':5,'output_tokens':3}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    reply=p.request_profile(profile,messages,use_cache=False)
    assert reply['content']=='{"ok":true}' and reply['finish_reason']=='length'
    assert reply['usage']['prompt_tokens']==35 and reply['usage']['cached_tokens']==20
    assert p.endpoint(profile.model_copy(update={'base_url':'https://a.invalid/v1/messages'}),'messages')=='https://a.invalid/v1/messages'

def test_profile_registry_switching_keeps_chat_and_embedding_separate_and_secrets_private():
    def save(name,protocol='openai_chat_completions',kind='chat',**kw):
        return ps.save({'kind':kind,'provider_name':name,'base_url':'https://fixture.invalid/v1','model_id':name,'api_key':'SECRET_KEY','protocol':protocol,**kw})
    registry=save('chat-a');pid=registry['active_chat'];assert ps.selected('chat').model_id=='chat-a'
    registry=save('claude',protocol='anthropic_messages');claude=registry['profiles'][-1]['id'];ps.activate(claude)
    assert ps.selected('chat').protocol=='anthropic_messages'
    embedding=save('vector',protocol='openai_embeddings',kind='embedding')['profiles'][-1]['id'];ps.activate(embedding)
    assert ps.selected('chat').model_id=='claude' and ps.selected('embedding').model_id=='vector'
    assert 'SECRET_KEY' not in json.dumps(ps.public())
    save('renamed',id=pid,api_key='');assert ps.get(pid)['api_key']=='SECRET_KEY'
    with pytest.raises(ValueError):save('bad',id=pid,api_key='',base_url='https://newhost.invalid')
    with pytest.raises(ValueError):save('bad',protocol='anthropic_messages',kind='embedding')
    ps.activate(pid);ps.delete(claude);assert ps.selected('chat').api_key=='SECRET_KEY'

def test_resumable_pipeline_new_paper_analysis_and_embedding_are_once_only(monkeypatch):
    q('a');q('b')
    with db.connection() as c:c.execute("DELETE FROM question_knowledge WHERE question_id='b'")
    monkeypatch.setattr(v,'ready',lambda _:True);monkeypatch.setattr(v,'embed',encoder)
    monkeypatch.setattr(p,'load_profile',lambda:remote(protocol='openai_chat_completions'));calls=[]
    def analyse(qs,*a,**kw):
        calls.append(len(qs));return ({x['id']:{'question_id':x['id'],'question_text':x['text'],'uncertain':False,'has_diagram':False,'topic':'等价无穷小','problem':{},'methods':[]} for x in qs},{'model_id':'fixture'})
    monkeypatch.setattr(k,'analyse',analyse)
    jid=v.enqueue();assert v.enqueue()==jid;v.process(jid)
    assert calls==[1] and v.stats()['indexed']==2
    with db.connection() as c:assert c.execute('SELECT status FROM embedding_jobs WHERE id=?',(jid,)).fetchone()[0]=='complete'
    jid=v.enqueue();v.process(jid);assert calls==[1]

def test_recommend_uses_knowledge_vectors_without_chat_request(monkeypatch):
    q('a');q('b');monkeypatch.setattr(v,'embed',encoder);v.index_questions(v.all_questions());service.init()
    monkeypatch.setattr(service,'prepare',lambda q,cancelled:{**q,'prepared':True,'kind':'scratch'})
    session=service.open_session('a')
    from backend.ai import difficulty
    with db.connection() as c:
        for qid in ('a','b'):difficulty.put(k.bank_question(c,qid),{'level':3,'reason':'单知识点常规判断','confidence':'high','calculation_load':'light'})
    monkeypatch.setattr(service,'request_profile',lambda *a,**kw:pytest.fail('vector recommendation must not call LLM'))
    result=service.recommend(session['id'])
    assert result['question_id']=='b' and result['retrieval']=='knowledge_embedding'

def test_import_enqueues_default_index_and_preserves_original_assets(monkeypatch,tmp_path):
    import pymupdf
    from backend.app import app
    queued=[];monkeypatch.setattr(v,'enqueue',lambda paper_id=None,**kw:(queued.append((paper_id,kw)) or 'job-new'))
    document=pymupdf.open();page=document.new_page();page.insert_text((72,72),'1. Calculate the derivative of x squared.');content=document.tobytes();document.close()
    with TestClient(app) as client:
        response=client.post('/api/papers/import',data={'subject':'数学二'},files={'file':('sample.pdf',content,'application/pdf')})
        assert response.status_code==200,response.text
        item=response.json();assert item['embedding_job']=='job-new' and queued==[(item['id'],{'automatic':True})]
        assert (db.DATA/'uploads'/item['id']/'source.pdf').read_bytes()==content
        monkeypatch.setattr(v,'enqueue',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('queue failure')))
        response=client.post('/api/papers/import',data={'subject':'408'},files={'file':('another.pdf',content,'application/pdf')})
        assert response.status_code==200 and '索引' in response.json()['warnings'][-1]
        assert (db.DATA/'uploads'/response.json()['id']/'source.pdf').is_file()
