import io,json,time,zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import db,grading
from backend.app import app
from backend.ai import provider

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE',str(tmp_path/'provider.json'))
    with TestClient(app) as c:yield c

def add(c,kind='subjective',cap=6,key='2x',paper=None):
    result=c.post('/api/questions',json={'number':'1','text':('填空题' if kind=='fill' else '解答题')+f' · {cap}分\n求 f(x)=x^2 的导数。','subject':'数学二','reference_answer':key,'confirmed':True}).json()
    with db.connection() as con:
        if paper:con.execute('UPDATE questions SET paper_id=? WHERE id=?',(paper,result['id']))
        con.execute('INSERT INTO question_grading VALUES(?,?)',(result['id'],json.dumps({'kind':kind,'max_points':cap,'answer_key':key,'solution':key,'source':'测试参考答案'})))
    return result['id']

def image(c,q,color='white'):
    raw=io.BytesIO();Image.new('RGB',(500,300),color).save(raw,'PNG')
    response=c.post('/api/grading/questions/'+q+'/images',files={'file':('answer.png',raw.getvalue(),'image/png')})
    assert response.status_code==200,response.text
    return response.json()

def finish(c,b):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        state=c.get('/api/grading/batches/'+b['id']).json()
        if state['status']=='complete':return state
        time.sleep(.02)
    pytest.fail('grading did not finish')

def check(c,q,**answer):
    response=c.post('/api/grading/questions/'+q+'/check',json={'request_id':grading.uid(),**answer})
    assert response.status_code==200,response.text
    return finish(c,response.json())

RULES={'source':'手动核对评分要求','instructions':'法则与结果分别得分；不要替学生补步骤。','verified':True,
       'criteria':[{'id':'method','description':'给出幂函数求导法则','max_points':2},
                   {'id':'result','description':'正确写出导数 2x','max_points':4}]}

def mock_ai(monkeypatch,result,seen=None):
    monkeypatch.setattr(provider,'load_profile',lambda:object())
    def request(p,m,**kw):
        if seen is not None:seen.append(m)
        raw=json.dumps(result);kw['validator'](raw);return {'content':raw,'cache_hit':False}
    monkeypatch.setattr(provider,'request_profile',request)

def test_photo_ownership_validation_persistent_drafts_history_and_backup(client):
    q=add(client);other=add(client);photo=image(client,q)
    assert client.get(photo['url']).status_code==200
    path=db.DATA/'uploads'/('answer-images/'+photo['id']+'/answer.png');assert path.exists()
    assert client.put('/api/grading/questions/'+other+'/draft',json={'version':0,'images':[photo['id']]}).status_code==422
    saved=client.put('/api/grading/questions/'+q+'/draft',json={'version':0,'images':[photo['id']]}).json()
    assert saved['version']==1 and saved['images'][0]['id']==photo['id']
    assert client.put('/api/grading/questions/'+q+'/draft',json={'version':0,'images':[]}).status_code==409
    assert client.post('/api/grading/questions/'+q+'/record',json={'images':[photo['id']]}).status_code==200
    history=client.get('/api/grading/questions/'+q).json()['history'];assert history[0]['images'][0]['sha256']==photo['sha256']
    client.put('/api/grading/questions/'+q+'/draft',json={'version':1,'images':[]})
    assert path.exists() and client.get('/api/grading/questions/'+q).json()['history'][0]['images']
    backup=zipfile.ZipFile(io.BytesIO(client.get('/api/backup').content));assert 'uploads/answer-images/'+photo['id']+'/answer.png' in backup.namelist()
    assert client.post('/api/grading/questions/'+q+'/images',files={'file':('bad.jpg',b'not image','image/jpeg')}).status_code==422
    assert client.post('/api/questions/'+other+'/merge',json={'other_id':q}).status_code==409

def test_strict_criteria_scores_are_auto_counted_and_every_point_has_actual_evidence(client,monkeypatch):
    q=add(client);assert client.put('/api/grading/questions/'+q+'/rules',json=RULES).status_code==200
    result={'score':6,'comment':'法则与计算均正确','criteria':[{'id':'method','score':2,'evidence':'幂函数求导','reason':'已说明法则'},
         {'id':'result','score':4,'evidence':'2x','reason':'结论正确'}]}
    mock_ai(monkeypatch,result)
    b=check(client,q,answer='2x',reasoning='使用幂函数求导')
    assert b['summary']['confirmed_score']==6 and b['summary']['final']
    assert b['results'][0]['rubric_strict'] and b['results'][0]['reviewer']=='ai'
    result['criteria'][0]['evidence']='学生没有写的步骤'
    assert check(client,q,answer='2x',reasoning='使用幂函数求导')['results'][0]['score'] is None
    result['criteria'][0]['evidence']='幂函数求导';result['score']=5
    assert check(client,q,answer='2x',reasoning='使用幂函数求导')['summary']['pending']==1

def test_score_caps_dependency_binary_rules_and_missing_criteria_cannot_be_bypassed(client,monkeypatch):
    q=add(client);rules=json.loads(json.dumps(RULES));rules['criteria'][1]['depends_on']=['method'];rules['criteria'][1]['mode']='all_or_nothing'
    assert client.put('/api/grading/questions/'+q+'/rules',json=rules).status_code==200
    responses=[{'score':4,'comment':'缺方法','criteria':[{'id':'method','score':0,'reason':'缺法则'},{'id':'result','score':4,'evidence':'2x','reason':'正确'}]},
     {'score':5,'comment':'非零整分','criteria':[{'id':'method','score':2,'evidence':'法则','reason':'正确'},{'id':'result','score':3,'evidence':'2x','reason':'正确'}]},
     {'score':6,'comment':'多给分','criteria':[{'id':'method','score':3,'evidence':'法则','reason':'正确'},{'id':'result','score':3,'evidence':'2x','reason':'正确'}]},
     {'score':4,'comment':'缺一项','criteria':[{'id':'result','score':4,'evidence':'2x','reason':'正确'}]}]
    for result in responses:
        mock_ai(monkeypatch,result);assert check(client,q,answer='2x',reasoning='法则')['summary']['pending']==1
    rules['criteria'][1]['max_points']=5
    assert client.put('/api/grading/questions/'+q+'/rules',json=rules).status_code==422

def test_image_only_answer_is_not_blank_and_is_passed_as_student_work_to_vision(client,monkeypatch):
    q=add(client,kind='fill',cap=5);photo=image(client,q);seen=[]
    mock_ai(monkeypatch,{'score':5,'comment':'图片答案正确','recognized_answer':'2x'},seen)
    b=check(client,q,images=[photo['id']]);g=b['results'][0]
    assert g['score']==5 and g['recognized_answer']=='2x' and g['answer_images'][0]['id']==photo['id']
    content=seen[0][-1]['content'];assert any(part.get('text','').startswith('学生作答') for part in content)
    assert any(part.get('type')=='image_url' for part in content)
    mock_ai(monkeypatch,{'score':5,'comment':'不清晰','uncertain':True,'uncertainties':['指数无法读清']})
    assert check(client,q,images=[photo['id']])['results'][0]['score'] is None
    mock_ai(monkeypatch,{'score':5,'comment':'假装已识别但没有转录'})
    assert check(client,q,images=[photo['id']])['summary']['pending']==1

def test_whole_paper_images_snapshot_and_retry_identity_survive_removal(client,monkeypatch):
    with db.connection() as con:con.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('p','图像整卷','数学二','',grading.now(),'[]'))
    q=add(client,paper='p');photo=image(client,q);second=image(client,q,'gray')
    client.put('/api/grading/questions/'+q+'/rules',json=RULES)
    r=client.post('/api/grading/papers/p/runs',json={}).json()
    a={q:{'answer':'2x','reasoning':'幂函数求导','images':[photo['id']]}}
    saved=client.put('/api/grading/runs/'+r['id'],json={'version':0,'answers':a}).json();assert saved['answers']==a
    mock_ai(monkeypatch,{'score':6,'comment':'正确','recognized_answer':'2x','criteria':[{'id':'method','score':2,'evidence':'幂函数求导','reason':'说明法则'},{'id':'result','score':4,'evidence':'2x','reason':'结果正确'}]})
    b=finish(client,client.post('/api/grading/runs/'+r['id']+'/grade',json={'version':1,'request_id':'paper-image'}).json())
    assert b['summary']['confirmed_score']==6
    assert client.get('/api/grading/runs/'+r['id']).json()['graded_answers_match']
    a[q]['images']=[second['id']]
    client.put('/api/grading/runs/'+r['id'],json={'version':1,'answers':a})
    assert not client.get('/api/grading/runs/'+r['id']).json()['graded_answers_match']
    assert client.post('/api/grading/runs/'+r['id']+'/grade',json={'version':2,'request_id':'paper-image'}).status_code==409
    assert client.get('/api/grading/questions/'+q).json()['history'][0]['images'][0]['id']==photo['id']

def test_auto_detection_of_choice_options_returns_letters_and_text(client):
    q=client.post('/api/questions',json={'number':'2','text':'请选择正确结果\n(A) $x$\n(B) $2x$\n(C) $3x$\n(D) $4x$','subject':'数学二','reference_answer':'B'}).json()['id']
    result=client.get('/api/grading/questions/'+q).json()
    assert result['spec']['kind']=='mcq' and result['options'][1]=={'value':'B','text':'$2x$'}

def test_missing_math_points_recovered_from_saved_source_without_changing_answers(client):
    source=db.DATA/'sources/math';source.mkdir(parents=True)
    (source/'math2-2026.html').write_text('<html><main><h4>填空题</h4><p>11～16小题，每小题5分，共30分。</p><h5 id="17">17</h5><p>（本题满分10分）</p></main></html>',encoding='utf-8')
    with db.connection() as c:
        c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('real-math2-2026','数学二真题','数学二','',grading.now(),'[]'))
        for n in (11,17):c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',(f'real-math2-2026-q{n}','real-math2-2026',str(n),'填空题' if n==11 else '解答题','[]','2x','数学二',1,grading.now()))
    q=client.get('/api/grading/questions/real-math2-2026-q11').json()
    assert q['spec']['max_points']==5 and q['spec']['points_known']
    assert client.get('/api/grading/questions/real-math2-2026-q17').json()['spec']['max_points']==10
    assert client.get('/api/questions/real-math2-2026-q11').json()['reference_answer']=='2x'

def test_refresh_exam_rules_copies_answers_and_preserves_original_snapshot(client):
    with db.connection() as c:c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',('renew','更新评分试卷','数学二','',grading.now(),'[]'))
    q=add(client,paper='renew');r=client.post('/api/grading/papers/renew/runs',json={}).json()
    answers={q:{'answer':'2x','reasoning':'幂函数求导'}}
    client.put('/api/grading/runs/'+r['id'],json={'version':0,'answers':answers})
    client.put('/api/grading/questions/'+q+'/rules',json=RULES)
    assert not client.get('/api/grading/runs/'+r['id']).json()['scoring_snapshot_current']
    new=client.post('/api/grading/runs/'+r['id']+'/refresh-scoring',json={}).json()
    assert new['id']!=r['id'] and new['answers']==answers and new['scoring_snapshot_current']
    old=client.get('/api/grading/runs/'+r['id']).json()
    assert old['answers']==answers and 'scoring_rules' not in old['questions'][0]['spec']
