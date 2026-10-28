import json
import sqlite3
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import db,grading
from backend.app import app
from backend.ai import knowledge as k,service,cache,provider
from backend.ai.catalog import public
from backend.ai.context import messages
from backend.ai.adaptive import Reply,initial

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    with TestClient(app) as c:yield c

def make(c,image=False,kind='limit'):
    q=c.post('/api/questions',json={'number':'1','text':'2024 年 数学二 · 填空题 · 5分\n请阅读下方原始题图，公式以图片为准。' if image else '求 sin(x)/x 在 x→0 的极限','subject':'数学二','reference_answer':'1','confirmed':not image}).json()
    if image:
        Image.new('RGB',(600,400),'white').save(db.DATA/'uploads/q.png')
        with db.connection() as con:con.execute('UPDATE questions SET images=? WHERE id=?',('["q.png"]',q['id']))
    with db.connection() as con:
        q=k.bank_question(con,q['id'])
    payload={'question_id':q['id'],'question_text':'求 $\\sin(x)/x$ 在 $x\\to0$ 的极限','uncertain':False,'has_diagram':False,'topic':'三角函数极限','problem':{'kind':kind,'expression':'sin(x)/x' if kind=='limit' else None,'skill_ids':['math2.limit.indeterminate']},'methods':[{'name':'泰勒展开','first_question':'先判断保留到几阶？','checkpoints':['检查主导项']}],'private_solution':'答案秘密：1；利用泰勒展开后取极限。','rubric':'核对主导项与最后的极限','solution_basis':'reference','reference_source':'录入的参考解析'}
    k.put(q,payload,'测试参考解析');return q,payload

def test_durable_knowledge_clear_cache_restart_and_prepare_no_network(client,monkeypatch):
    q,p=make(client)
    def remote(*a,**kw):pytest.fail('knowledge hit must not call provider')
    monkeypatch.setattr(service,'request_profile',remote)
    cache.clear();k.init();snapshot=service.snapshot(q)
    prepared=service.prepare(snapshot,None)
    assert prepared['knowledge_hit'] and prepared['config']['original_expression']=='sin(x)/x'
    assert prepared['skills']==['math2.limit.indeterminate']
    assert client.delete('/api/ai/cache').json()['knowledge']['stored_questions']==1
    assert k.get(q)['private_solution']==p['private_solution']
    assert client.get('/api/ai/knowledge').json()['metrics']['prepare_hits']==1
    assert '答案秘密' not in json.dumps(messages('instruction',{'question':public(prepared)}),ensure_ascii=False)

def test_changed_question_reference_or_image_never_reuses_old_analysis(client):
    q,p=make(client,image=True)
    assert k.get(q)
    for patch in [{'text':q['text']+'改题'},{'reference_answer':'2'},{'spec':{**q['spec'],'max_points':6}}]:assert k.get({**q,**patch}) is None
    Image.new('RGB',(610,400),'black').save(db.DATA/'uploads/q.png')
    assert k.get(q) is None
    assert not k.prepared(service.snapshot(q))

def test_ocr_confirm_promotes_analysis_and_preserves_points(client,monkeypatch):
    q,p=make(client,image=True)
    monkeypatch.setattr(service,'request_profile',lambda *a,**kw:pytest.fail('cached OCR hit must not call provider'))
    result=client.post('/api/questions/'+q['id']+'/ai/transcribe',json={}).json()
    assert result['knowledge_hit'] and result['text']==p['question_text']
    reply=client.put('/api/questions/'+q['id']+'/ai/transcription',json={'text':result['text'],'fingerprint':result['fingerprint']})
    assert reply.status_code==200,reply.text
    with db.connection() as con:new=k.bank_question(con,q['id'])
    assert new['spec']['max_points']==5 and new['spec']['kind']=='fill'
    assert k.get(new) and service.prepare(service.snapshot(new),None)['knowledge_hit']

def test_manually_corrected_ocr_is_not_aliased_to_old_method(client):
    q,p=make(client,image=True)
    response=client.put('/api/questions/'+q['id']+'/ai/transcription',json={'text':'另一道题：求 x 的导数','fingerprint':service.fingerprint(q)})
    assert response.status_code==200
    with db.connection() as con:new=k.bank_question(con,q['id'])
    assert k.get(new) is None

def test_grading_uses_cached_text_and_rubric_and_omits_pure_text_image(client,monkeypatch):
    q,p=make(client,image=True,kind='scratch')
    q['spec']['kind']='subjective'
    # Persist the cap/kind before building the corresponding analysis fingerprint.
    with db.connection() as con:con.execute('INSERT INTO question_grading VALUES(?,?)',(q['id'],grading.dumps(q['spec'])))
    k.put(q,p,'测试参考解析')
    monkeypatch.setattr(provider,'load_profile',lambda:object())
    def request(profile,msgs,**kwargs):
        assert isinstance(msgs[-1]['content'],str),'pure text should not resend its image'
        data=json.loads(msgs[-1]['content']);assert data['question']==p['question_text'] and data['rubric']==p['rubric']
        raw=json.dumps({'score':3,'comment':'缺少过程','points':[]});kwargs['validator'](raw);return {'content':raw}
    monkeypatch.setattr(provider,'request_profile',request)
    result=grading.evaluate(q,{'answer':'1','reasoning':'先用泰勒'})
    assert result['status']=='suggested' and result['score']==3

def test_cached_solution_only_available_after_explicit_solution_or_answer_exposure(client,monkeypatch):
    from backend.ai import adaptive
    q,p=make(client);prepared=service.prepare(service.snapshot(q),None)
    contexts=[]
    def reply(context,*a,**kw):contexts.append(context.copy());return Reply(message='先判断关键条件',next_question='下一步呢？'),{'usage':{}}
    monkeypatch.setattr(adaptive,'model_reply',reply)
    adaptive.run(prepared,initial(prepared),'我想用泰勒展开',[],[])
    assert 'review_reference' not in contexts[0]
    assert '答案秘密' not in json.dumps(contexts[0],ensure_ascii=False)
    adaptive.run(prepared,initial(prepared),'给我完整讲解',[],[])
    assert contexts[-1]['review_reference']['solution']==p['private_solution']

def test_knowledge_in_original_backup_and_merge_discards_only_derived_cache(client,tmp_path):
    q,p=make(client);other,_=make(client)
    response=client.post('/api/questions/'+q['id']+'/merge',json={'other_id':other['id']});assert response.status_code==200,response.text
    with db.connection() as con:assert con.execute('SELECT count(*) FROM question_knowledge').fetchone()[0]==0
    q,p=make(client)
    import zipfile,io
    response=client.get('/api/backup')
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:z.extract('mathmaster.db',tmp_path/'restore')
    restore=sqlite3.connect(tmp_path/'restore/mathmaster.db');assert restore.execute('SELECT count(*) FROM question_knowledge').fetchone()[0]==1

def test_local_ocr_is_corrected_once_then_uses_confirmed_knowledge(client,monkeypatch):
    q,p=make(client,image=True,kind='scratch')
    p.update(question_text='OCR corrupted formula',uncertain=True,warnings=['[local_ocr_only]'])
    k.put(q,p,'local OCR')
    calls=[]
    def request(*args,**kwargs):
        calls.append(1)
        return {'content':json.dumps({'text':'求 $\\sin(x)/x$ 在零点的极限','uncertain':False})}
    monkeypatch.setattr(service,'request_profile',request)
    result=service.transcribe(q['id']);assert len(calls)==1 and not result.get('knowledge_hit')
    r=client.put('/api/questions/'+q['id']+'/ai/transcription',json={'text':result['text'],'fingerprint':result['fingerprint']})
    assert r.status_code==200
    result=service.transcribe(q['id']);assert len(calls)==1 and result['knowledge_hit']
    with db.connection() as c:new=k.bank_question(c,q['id'])
    assert k.get(new)['question_text']==result['text']
    assert '[local_ocr_only]' not in k.get(new)['warnings']


def test_reference_images_reach_grader_and_changes_invalidate_knowledge(client,monkeypatch):
    q,p=make(client,image=True,kind='scratch')
    Image.new('RGB',(100,100),'white').save(db.DATA/'uploads/reference.png')
    q['spec'].update(kind='fill',answer_key='',solution='',reference_images=['reference.png'],reference_ocr_draft=True)
    q['reference_answer']=''
    with db.connection() as c:
        c.execute('UPDATE questions SET reference_answer=? WHERE id=?',('',q['id']))
        c.execute('INSERT INTO question_grading VALUES(?,?)',(q['id'],grading.dumps(q['spec'])))
        q=k.bank_question(c,q['id'])
    k.put(q,p,'local source')
    monkeypatch.setattr(provider,'load_profile',lambda:object())
    def request(profile,messages,**kwargs):
        content=messages[-1]['content'];labels=[x['text'] for x in content if x['type']=='text']
        assert any('原书参考解析图片' in x for x in labels)
        assert sum(x['type']=='image_url' for x in content)==1
        return {'content':json.dumps({'score':5,'comment':'已对照原书解析图片核对','points':[]})}
    monkeypatch.setattr(provider,'request_profile',request)
    result=grading.evaluate(q,{'answer':'1','reasoning':''})
    assert result['status']=='suggested' and result['score']==5
    assert client.get('/api/questions/'+q['id']).json()['reference_images']==['reference.png']
    Image.new('RGB',(110,100),'black').save(db.DATA/'uploads/reference.png')
    assert k.get(q) is None

def test_solution_image_only_enters_explicit_review_messages(client):
    Image.new('RGB',(100,100),'white').save(db.DATA/'uploads/solution.png')
    q,p=make(client)
    blind=messages('rules',{'question':public({**q,'private_analysis':{'images':['solution.png']}}),'user_text':'第一步怎么想'})
    assert all(isinstance(m['content'],str) for m in blind)
    review=messages('rules',{'question':public(q),'review_reference':{'solution':'以原书为准','images':['solution.png']}})
    assert any(x['type']=='image_url' for x in review[-1]['content'])
    assert 'solution.png' not in json.dumps(review)

def test_bulk_pdf_import_is_idempotent_and_preserves_learner_edits(client):
    from scripts.import_local_pdf_library import install
    q,p=make(client,image=True,kind='scratch')
    row={**q,'id':'local-test-new-q001','paper_id':'local-test-paper','confirmed':False,'knowledge':{**p,'question_id':'local-test-new-q001'}}
    plan={'papers':[{'id':'local-test-paper','title':'本地数二试卷','subject':'数学二','filename':'test.pdf','warnings':[]}],'questions':[row]}
    first=install(plan);assert first['created']==1
    with db.connection() as c:
        c.execute('UPDATE questions SET reference_answer=? WHERE id=?',('用户核对后的答案',row['id']))
        c.execute('INSERT INTO attempts(question_id,answer,notes,updated_at) VALUES(?,?,?,?)',(row['id'],'B','我已有的解题过程',k.now()))
    second=install(plan);assert second['created']==0 and second['preserved_existing']==1
    with db.connection() as c:
        assert c.execute('SELECT reference_answer FROM questions WHERE id=?',(row['id'],)).fetchone()[0]=='用户核对后的答案'
        assert c.execute('SELECT notes FROM attempts WHERE question_id=?',(row['id'],)).fetchone()[0]=='我已有的解题过程'
        assert c.execute('SELECT count(*) FROM questions WHERE id=?',(row['id'],)).fetchone()[0]==1
