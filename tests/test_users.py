import io
import json
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend import db, grading
from backend.app import app
from backend.identity import current_user
from backend.user_storage import PERSONAL_TABLES, route_sql
from backend.ai import service, vectors


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE',str(tmp_path/'provider.json'))
    monkeypatch.setattr(vectors,'ready',lambda p:False)
    with TestClient(app) as client:yield client


def register(client,name):
    response=client.post('/api/users',json={'name':name},headers={'X-MathMaster-User':'zzy'})
    assert response.status_code==201,response.text
    return response.json()['id']


def headers(uid):return {'X-MathMaster-User':uid}


def test_three_password_free_users_and_concurrent_registration_limit(client):
    registry=client.get('/api/users').json()
    assert registry['users']==[{'id':'zzy','name':'zzy'}] and registry['remaining']==2
    assert client.post('/api/users',json={'name':'  ZZY  '}).status_code==409
    assert client.post('/api/users',json={'name':'  '}).status_code==422
    assert client.post('/api/users',json={'name':'bad\nname'}).status_code==422
    # Test clients without lifespan avoid restarting global workers per request.
    def create(i):
        c=TestClient(app)
        return c.post('/api/users',json={'name':'guest-'+str(i)},headers=headers('zzy')).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(create,range(4)))
    assert results.count(201)==2 and results.count(409)==2
    assert client.get('/api/users',headers=headers('zzy')).json()['remaining']==0
    assert client.post('/api/users/missing/select',headers=headers('zzy')).status_code==404
    assert client.get('/api/practice/recent',headers=headers('missing')).status_code==409


def test_shared_questions_separate_answers_history_sessions_images_and_preferences(client,tmp_path):
    zzy=headers('zzy')
    qid=client.post('/api/questions',json={'text':'求 x² 的导数','subject':'数学二'},headers=zzy).json()['id']
    client.put('/api/questions/'+qid+'/attempt',json={'answer':'zzy-answer','notes':'zzy-note','draft':'[]','status':'已完成','wrong':True},headers=zzy)
    client.post('/api/practice/'+qid+'/visit',json={},headers=zzy)
    zzy_session=client.post('/api/questions/'+qid+'/ai',json={},headers=zzy)
    assert zzy_session.status_code==200,zzy_session.text
    guest=register(client,'小明');h=headers(guest)
    assert client.get('/api/questions/'+qid,headers=h).json()['attempt']=={}
    assert client.get('/api/practice/recent',headers=h).json()==[]
    assert client.get('/api/stats',headers=h).json()['completed']==0
    assert client.get('/api/ai/sessions/'+zzy_session.json()['id'],headers=h).status_code==404
    client.put('/api/questions/'+qid+'/attempt',json={'answer':'guest-answer','notes':'guest-note','draft':'[]'},headers=h)
    client.post('/api/practice/'+qid+'/visit',json={},headers=h)
    assert client.get('/api/questions/'+qid,headers=zzy).json()['attempt']['answer']=='zzy-answer'
    assert client.get('/api/questions/'+qid,headers=h).json()['attempt']['answer']=='guest-answer'
    assert client.get('/api/questions?wrong=true',headers=h).json()==[]
    assert len(client.get('/api/questions?wrong=true',headers=zzy).json())==1
    guest_session=client.post('/api/questions/'+qid+'/ai',json={},headers=h).json()
    assert guest_session['id']!=zzy_session.json()['id']
    assert client.get('/api/ai/sessions/'+guest_session['id'],headers=zzy).status_code==404
    assert client.post('/api/ai/sessions/'+guest_session['id']+'/cancel',json={},headers=zzy).status_code==404
    client.post('/api/grading/questions/'+qid+'/record',json={'answer':'guest-record'},headers=h)
    assert client.get('/api/grading/questions/'+qid,headers=zzy).json()['history']==[]
    assert client.get('/api/grading/questions/'+qid,headers=h).json()['history'][0]['answer']=='guest-record'
    png=io.BytesIO();Image.new('RGB',(8,8),'white').save(png,'PNG')
    picture=client.post('/api/grading/questions/'+qid+'/images',files={'file':('answer.png',png.getvalue(),'image/png')},headers=h).json()
    assert client.get(picture['url'],headers=zzy).status_code==404
    assert client.get(picture['url'],headers=h).status_code==200
    assert client.get('/api/grading/questions/'+qid+'/images?ids='+picture['id'],headers=zzy).status_code==422
    assert client.put('/api/grading/questions/'+qid+'/draft',json={'images':[picture['id']],'version':0},headers=h).status_code==200
    assert client.get('/api/grading/questions/'+qid+'/draft',headers=zzy).json()['images']==[]
    pids=[]
    for model in ('model-a','model-b'):
        saved=client.post('/api/ai/profiles',json={'kind':'chat','provider_name':model,'base_url':'https://fixture.invalid/v1','model_id':model,'api_key':'test-secret','protocol':'openai_chat_completions'},headers=zzy).json()
        pids.append(next(p['id'] for p in saved['profiles'] if p['model_id']==model))
    client.post('/api/ai/profiles/'+pids[0]+'/activate',json={},headers=zzy)
    client.post('/api/ai/profiles/'+pids[1]+'/activate',json={},headers=h)
    assert client.get('/api/ai/provider',headers=zzy).json()['model_id']=='model-a'
    assert client.get('/api/ai/provider',headers=h).json()['model_id']=='model-b'
    assert client.post('/api/users/zzy/select',json={},headers=h).status_code==200
    assert client.get('/api/ai/provider').json()['model_id']=='model-a'
    assert client.post('/api/users/'+guest+'/select',json={},headers=zzy).status_code==200
    assert client.get('/api/ai/provider').json()['model_id']=='model-b'
    # Per-page headers retain ownership even if another tab changes the cookie.
    assert client.get('/api/questions/'+qid,headers=zzy).json()['attempt']['answer']=='zzy-answer'
    guest_backup=client.get('/api/backup',headers=h)
    assert guest_backup.status_code==200
    archive=zipfile.ZipFile(io.BytesIO(guest_backup.content))
    restore_path=tmp_path/'restored.db';restore_path.write_bytes(archive.read('mathmaster.db'))
    restored=sqlite3.connect(restore_path)
    assert restored.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    assert restored.execute('SELECT answer FROM user_'+guest+'__attempts').fetchone()[0]=='guest-answer'
    assert restored.execute('PRAGMA foreign_key_check').fetchall()==[]
    restored.close()
    zzy_backup=zipfile.ZipFile(io.BytesIO(client.get('/api/backup',headers=zzy).content))
    assert not any('answer-images/' in name for name in zzy_backup.namelist())
    with db.connection(shared=True) as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_background_ai_job_keeps_originating_user_after_selection_changes(client,monkeypatch):
    guest=register(client,'guest');h=headers(guest)
    qid=client.post('/api/questions',json={'text':'后台用户归属测试'},headers=h).json()['id']
    session=client.post('/api/questions/'+qid+'/ai',json={},headers=h).json()
    started=threading.Event();release=threading.Event();finished=threading.Event();seen=[]
    def work(before,event):
        started.set();release.wait(5)
        try:
            seen.append(current_user.get())
            with db.connection() as c:
                c.execute('INSERT INTO history VALUES(?,?,?,?,?,?)',('worker-history',qid,'test','{}','{}','2026-10-15'))
                c.execute('UPDATE ai_sessions SET busy=0 WHERE id=?',(before['id'],))
        finally:finished.set()
    monkeypatch.setattr(service,'work',work)
    assert client.post('/api/ai/sessions/'+session['id']+'/turns',json={'text':'test','request_id':'test','version':0},headers=h).status_code==202
    assert started.wait(5)
    client.post('/api/users/zzy/select',json={},headers=h)
    release.set();assert finished.wait(5)
    assert seen==[guest]
    assert client.get('/api/math/history',headers=headers('zzy')).json()==[]
    assert client.get('/api/math/history',headers=h).json()[0]['id']=='worker-history'


def test_routing_preserves_literals_parameters_and_existing_zzy_tables(client):
    uid=register(client,'sql-user');tag='user_'+uid+'__'
    sql="SELECT 'history', \"history\".* FROM history -- attempts\n WHERE id=?"
    assert route_sql(sql,uid)==f"SELECT 'history', \"{tag}history\".* FROM {tag}history -- attempts\n WHERE id=?"
    assert route_sql(sql,'zzy')==sql
    with db.connection(shared=True) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert PERSONAL_TABLES.issubset(tables)
        assert all(tag+t in tables for t in PERSONAL_TABLES)
    token=current_user.set(uid)
    try:
        with db.connection() as c:
            assert c.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
            assert c.cursor().execute('SELECT count(*) FROM ai_sessions').fetchone()[0]==0
    finally:current_user.reset(token)


def test_restart_keeps_users_records_and_model_choices(client):
    guest=register(client,'persistent-user');h=headers(guest)
    qid=client.post('/api/questions',json={'text':'重启后保留'},headers=h).json()['id']
    client.put('/api/questions/'+qid+'/attempt',json={'answer':'persisted'},headers=h)
    saved=client.post('/api/ai/profiles',json={'kind':'chat','provider_name':'Model','base_url':'https://fixture.invalid/v1','model_id':'persistent-model','api_key':'key','protocol':'openai_chat_completions'},headers=headers('zzy')).json()
    pid=next(p['id'] for p in saved['profiles'] if p['model_id']=='persistent-model')
    client.post('/api/ai/profiles/'+pid+'/activate',json={},headers=h)
    with TestClient(app) as restarted:
        assert restarted.get('/api/users',headers=h).json()['current_user']==guest
        assert restarted.get('/api/questions/'+qid,headers=h).json()['attempt']['answer']=='persisted'
        assert restarted.get('/api/questions/'+qid,headers=headers('zzy')).json()['attempt']=={}
        assert restarted.get('/api/ai/provider',headers=h).json()['model_id']=='persistent-model'


def test_background_grading_keeps_user_and_cannot_be_read_by_another_user(client,monkeypatch):
    guest=register(client,'grading-user');h=headers(guest)
    qid=client.post('/api/questions',json={'text':'选择题','subject':'408','reference_answer':'A'},headers=h).json()['id']
    with db.connection(shared=True) as c:
        c.execute('INSERT INTO question_grading VALUES(?,?)',(qid,json.dumps({'kind':'mcq','answer_key':'A','max_points':2})))
    original=grading.work;done=threading.Event();seen=[]
    def work(*args):
        try:seen.append(current_user.get());original(*args)
        finally:done.set()
    monkeypatch.setattr(grading,'work',work)
    response=client.post('/api/grading/questions/'+qid+'/check',json={'answer':'A','request_id':'user-grading'},headers=h)
    assert response.status_code==200,response.text
    bid=response.json()['id'];assert done.wait(5)
    assert seen==[guest]
    result=client.get('/api/grading/batches/'+bid,headers=h).json()
    assert result['status']=='complete' and result['results'][0]['score']==2
    assert client.get('/api/grading/batches/'+bid,headers=headers('zzy')).status_code==404
