import json
import time
import pytest
from fastapi.testclient import TestClient
from backend import db,grading
from backend.app import app
from backend.ai import provider

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    with TestClient(app) as c:yield c

def add(client,number='1',kind='mcq',key='A',points=2,paper=None):
    q=client.post('/api/questions',json={'number':number,'text':'测试题','subject':'408','reference_answer':key,'confirmed':True}).json()
    with db.connection() as c:
        if paper:c.execute('UPDATE questions SET paper_id=? WHERE id=?',(paper,q['id']))
        c.execute('INSERT INTO question_grading VALUES(?,?)',(q['id'],json.dumps({'kind':kind,'answer_key':key,'solution':key,'max_points':points,'source':'测试答案'})))
    return q['id']

def finish(client,b):
    end=time.monotonic()+20
    while time.monotonic()<end:
        b=client.get('/api/grading/batches/'+b['id']).json()
        if b['status']=='complete':return b
        time.sleep(.03)
    pytest.fail('grade timeout')

def check(client,qid,answer,rid='one',reasoning=''):
    response=client.post('/api/grading/questions/'+qid+'/check',json={'answer':answer,'reasoning':reasoning,'request_id':rid})
    assert response.status_code==200,response.text
    return finish(client,response.json())

def test_saved_answer_history_current_check_and_no_attempt_overwrite(client):
    q=add(client)
    client.put(f'/api/questions/{q}/attempt',json={'answer':'A','notes':'原有笔记','draft':'[]','status':'作答中','wrong':False})
    assert client.post(f'/api/grading/questions/{q}/record',json={'answer':'选B','reasoning':'第一稿'}).status_code==200
    b=check(client,q,'选A')
    assert b['summary']['confirmed_score']==2 and b['summary']['final']
    assert client.get(f'/api/questions/{q}').json()['attempt']['notes']=='原有笔记'
    assert check(client,q,'B','two')['summary']['confirmed_score']==0
    history=client.get('/api/grading/questions/'+q).json()['history']
    assert len(history)==3 and history[-1]['answer']=='选B'
    assert client.post('/api/grading/questions/'+q+'/check',json={'answer':'C','request_id':'one'}).status_code==409
    assert len(client.get('/api/grading/questions/'+q).json()['history'])==3

def test_fill_actual_symbolic_check_and_invalid_choice_pending(client):
    q=add(client,kind='fill',key='x+x',points=5)
    assert check(client,q,'2*x')['summary']['confirmed_score']==5
    assert check(client,q,'2*x+1','wrong')['summary']['confirmed_score']==0
    q2=add(client,number='2')
    assert check(client,q2,'A或B','unclear')['summary']['pending']==1

def test_reference_version_conflict_never_auto_marks_or_calls_model(client,monkeypatch):
    q=add(client,key='D',points=5)
    with db.connection() as c:
        spec=grading.question(c,q)['spec'];spec['reference_issue']='题图与参考答案版本不一致，需核对原文。'
        c.execute('UPDATE question_grading SET spec=? WHERE question_id=?',(grading.dumps(spec),q))
    def unexpected(*a,**kw):pytest.fail('版本冲突不能通过模型猜测评分')
    monkeypatch.setattr(provider,'request_profile',unexpected)
    result=check(client,q,'D')['results'][0]
    assert result['status']=='pending' and result['score'] is None
    assert '版本不一致' in result['comment']

def test_new_reference_detected_and_cloned_without_rewriting_exam_history(client):
    with db.connection() as c:c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('new-ref','补答案整卷','数学二','',grading.now(),'[]'))
    q=add(client,key='',points=5,paper='new-ref')
    old=client.post('/api/grading/papers/new-ref/runs',json={}).json()
    answers={q:{'answer':'A','reasoning':'我的思路'}}
    client.put('/api/grading/runs/'+old['id'],json={'version':0,'answers':answers})
    with db.connection() as c:c.execute('UPDATE questions SET reference_answer=? WHERE id=?',('A',q))
    saved=client.get('/api/grading/runs/'+old['id']).json()
    assert not saved['scoring_snapshot_current']
    fresh=client.post('/api/grading/runs/'+old['id']+'/refresh-scoring',json={}).json()
    assert fresh['id']!=old['id'] and fresh['scoring_snapshot_current']
    assert fresh['answers']==saved['answers']
    assert fresh['questions'][0]['spec']['answer_key']=='A'
    assert client.get('/api/grading/runs/'+old['id']).json()==saved
    b=finish(client,client.post('/api/grading/runs/'+fresh['id']+'/grade',json={'version':0,'request_id':'new-answer'}).json())
    assert b['summary']['confirmed_score']==5

def test_suggestion_bounds_manual_confirmation_and_cache_namespace(client,monkeypatch):
    q=add(client,kind='subjective',key='证明过程',points=10)
    monkeypatch.setattr(provider,'load_profile',lambda:object())
    seen=[]
    def model(p,messages,**kwargs):
        seen.append(kwargs['cache_kind']);raw=json.dumps({'score':6,'comment':'缺少最终证明','points':['已有关键思路']});kwargs['validator'](raw);return {'content':raw,'cache_hit':True}
    monkeypatch.setattr(provider,'request_profile',model)
    b=check(client,q,'部分答案',reasoning='关键思路')
    assert seen==['grading'];assert b['summary']['confirmed_score']==0 and b['summary']['suggested_score']==6 and not b['summary']['final']
    path=f"/api/grading/batches/{b['id']}/questions/{q}"
    assert client.put(path,json={'score':11,'expected_updated_at':b['updated_at']}).status_code==422
    result=client.put(path,json={'score':7,'comment':'补充过程已核对','expected_updated_at':b['updated_at']}).json()
    assert result['summary']['final'] and result['summary']['confirmed_score']==7
    assert result['results'][0]['review_history'][0]['score']==6
    assert client.put(path,json={'score':1,'expected_updated_at':b['updated_at']}).status_code==409

def test_whole_paper_all_questions_resume_snapshot_no_reference_and_versions(client):
    with db.connection() as c:c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('p','408 测试整卷','408','',grading.now(),'[]'))
    ids=[add(client,str(n),'mcq' if n<=40 else 'subjective','A' if n!=41 else '',2 if n<=40 else 10,'p') for n in range(1,48)]
    r=client.post('/api/grading/papers/p/runs',json={}).json()
    assert len(r['questions'])==47
    answers={ids[0]:{'answer':'A','reasoning':''},ids[40]:{'answer':'已有答案','reasoning':''}}
    saved=client.put('/api/grading/runs/'+r['id'],json={'version':0,'answers':answers}).json()
    assert saved['version']==1
    assert client.put('/api/grading/runs/'+r['id'],json={'version':0,'answers':{}}).status_code==409
    assert client.get('/api/grading/runs/'+r['id']).json()['answers']==answers
    with db.connection() as c:c.execute('UPDATE questions SET reference_answer=? WHERE id=?',('B',ids[0]))
    assert client.post('/api/grading/runs/'+r['id']+'/grade',json={'version':0,'request_id':'stale'}).status_code==409
    b=finish(client,client.post('/api/grading/runs/'+r['id']+'/grade',json={'version':1,'request_id':'paper'}).json())
    assert b['summary']['max_points']==150 and b['summary']['count']==47
    assert b['summary']['confirmed_score']==2 and b['summary']['pending']==1 and not b['summary']['final']
    assert client.get('/api/grading/runs/'+r['id']).json()['graded_answers_match']
    assert len(client.get('/api/grading/questions/'+ids[0]).json()['history'])==1
    client.put('/api/grading/runs/'+r['id'],json={'version':1,'answers':{}})
    assert not client.get('/api/grading/runs/'+r['id']).json()['graded_answers_match']

def test_grading_reveal_marks_active_ai_evidence(client):
    q=add(client)
    # Avoid model calls: construct the same persisted schema as an existing tutor session.
    from backend.ai import service
    with db.connection() as c:
        c.execute('INSERT INTO ai_sessions(id,question_id,fingerprint,snapshot,state,created_at) VALUES(?,?,?,?,?,?)',('session',q,'f','{}','{"answer_exposed":false}',grading.now()))
    check(client,q,'A')
    with db.connection() as c:assert json.loads(c.execute('SELECT state FROM ai_sessions').fetchone()[0])['answer_exposed']

def test_concurrent_exam_save_prevents_lost_update(client):
    from concurrent.futures import ThreadPoolExecutor
    with db.connection() as c:c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('race','并发整卷','408','',grading.now(),'[]'))
    q=add(client,paper='race');r=client.post('/api/grading/papers/race/runs',json={}).json()
    def save(answer):return client.put('/api/grading/runs/'+r['id'],json={'version':0,'answers':{q:{'answer':answer,'reasoning':''}}})
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(save,['A','B']))
    assert sorted(response.status_code for response in results)==[200,409]
    assert client.get('/api/grading/runs/'+r['id']).json()['version']==1

def test_picture_supplied_to_model_and_invalid_ai_score_remains_pending(client,monkeypatch):
    from PIL import Image
    q=add(client,kind='subjective',key='参考证明',points=10)
    (db.DATA/'uploads').mkdir(exist_ok=True);Image.new('RGB',(500,300),'white').save(db.DATA/'uploads/question.png')
    with db.connection() as c:c.execute('UPDATE questions SET images=? WHERE id=?',('["question.png"]',q))
    monkeypatch.setattr(provider,'load_profile',lambda:object())
    def model(p,messages,**kwargs):
        content=messages[-1]['content'];assert len(content)==2 and content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        raw=json.dumps({'score':11,'comment':'不合法分数','points':[]});kwargs['validator'](raw)
    monkeypatch.setattr(provider,'request_profile',model)
    b=check(client,q,'作答')
    assert b['summary']['pending']==1 and b['results'][0]['score'] is None

def test_question_merge_keeps_answer_and_exam_records(client):
    target=add(client,number='1');source=add(client,number='2')
    assert client.post(f'/api/questions/{target}/merge',json={'other_id':source}).status_code==200
    recorded=add(client,number='3');client.post(f'/api/grading/questions/{recorded}/record',json={'answer':'A'})
    assert client.post(f'/api/questions/{target}/merge',json={'other_id':recorded}).status_code==409
    with db.connection() as c:c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('merge-exam','试卷','408','',grading.now(),'[]'))
    first=add(client,'4',paper='merge-exam');second=add(client,'5',paper='merge-exam')
    client.post('/api/grading/papers/merge-exam/runs',json={})
    assert client.post(f'/api/questions/{first}/merge',json={'other_id':second}).status_code==409

def test_inline_ocr_choices_are_split_only_when_all_four_are_ordered(monkeypatch):
    monkeypatch.setattr(grading.knowledge, 'get', lambda q: None)
    q={'text':'选择题\nA. 软件 B. 硬件 C. 计算机资源 D. 应用程序'}
    assert [o['text'] for o in grading.options(q)] == ['软件','硬件','计算机资源','应用程序']
    q['text']='选择题\nA. 第一项\nB. 第二项\nC. 第三项\nD. 第四项'
    assert [o['text'] for o in grading.options(q)] == ['第一项','第二项','第三项','第四项']
    q['text']='A. 段落中提到 B. 但不是完整选项'
    assert grading.options(q)[0]['text']=='段落中提到 B. 但不是完整选项'
