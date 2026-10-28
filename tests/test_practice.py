import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.app import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    with TestClient(app) as client:yield client


def create(client,number):
    return client.post('/api/questions',json={'number':number,'text':'计算 x²。'}).json()['id']


def test_recent_backfills_existing_work_and_visits_do_not_change_answers(client):
    assert client.get('/api/practice/recent').json()==[]
    first,second=create(client,'已作答'),create(client,'只打开')
    client.put(f'/api/questions/{first}/attempt',json={'answer':'答案','notes':'保留笔记','draft':'[]','status':'已完成'})
    assert client.get('/api/practice/recent').json()[0]['id']==first
    original=client.get(f'/api/questions/{first}').json()['attempt']
    for qid in [second,first,second]:
        assert client.post(f'/api/practice/{qid}/visit',json={}).status_code==200
    recent=client.get('/api/practice/recent').json()
    assert [q['id'] for q in recent]==[second,first]
    assert client.get(f'/api/questions/{second}').json()['attempt']=={}
    assert client.get(f'/api/questions/{first}').json()['attempt']==original
    assert not any(key in recent[0] for key in ['draft','answer','notes'])
    assert client.get('/api/practice/recent?limit=1').json()[0]['id']==second
    assert client.get('/api/practice/recent?limit=0').status_code==422
    assert client.post('/api/practice/missing/visit',json={}).status_code==404


def test_resume_neighbors_follow_paper_order_and_skip_other_papers(client):
    a,b,c,other=[create(client,n) for n in ['1','2','3','另一卷']]
    with db.connection() as conn:
        for pid in ['paper-a','paper-b']:
            conn.execute('INSERT INTO papers(id,title,subject,filename,created_at) VALUES(?,?,?,?,?)',(pid,pid,'数学一',pid+'.pdf','2026-10-01'))
        for qid in [a,b,c]:conn.execute('UPDATE questions SET paper_id=?,created_at=? WHERE id=?',('paper-a','2026-10-01',qid))
        conn.execute('UPDATE questions SET paper_id=?,created_at=? WHERE id=?',('paper-b','2026-10-01',other))
    for qid,direction,expected in [(a,'previous',None),(a,'next',b),(b,'previous',a),(b,'next',c),(c,'next',None)]:
        assert client.get(f'/api/practice/{qid}/neighbor?direction={direction}').json()=={'id':expected}
    assert client.get('/api/practice/missing/neighbor?direction=next').status_code==404
    assert client.get(f'/api/practice/{a}/neighbor?direction=bad').status_code==422
    client.post(f'/api/practice/{b}/visit',json={})
    # Deleting/merging a visited question must not leave an unusable resume link.
    with db.connection() as conn:conn.execute('DELETE FROM questions WHERE id=?',(b,))
    assert client.get('/api/practice/recent').json()==[]
