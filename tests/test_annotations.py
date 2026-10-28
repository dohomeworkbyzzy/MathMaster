import io
import json
import sqlite3
import zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import db
from backend.app import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    monkeypatch.setenv('MATHMASTER_START_INDEXER','0')
    monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE',str(tmp_path/'provider.json'))
    with TestClient(app,headers={'X-MathMaster-User':'zzy'}) as client:yield client


def create(client):
    qid=client.post('/api/questions',json={'text':'标注测试题','number':'1'}).json()['id']
    with db.connection() as c:c.execute('UPDATE questions SET images=? WHERE id=?',(json.dumps(['annotation.png']),qid))
    return qid


def stroke(id='stroke-1'):
    return {'id':id,'image':'annotation.png','tool':'pen','color':'#ff6b6b','width':3,'points':[{'x':.25,'y':.4},{'x':.6,'y':.4}]}


def test_annotations_preserve_source_and_draft_and_are_in_backup(client):
    qid=create(client)
    image=io.BytesIO();Image.new('RGB',(100,80),'white').save(image,'PNG');original=image.getvalue()
    (db.DATA/'uploads'/'annotation.png').write_bytes(original)
    client.put(f'/api/questions/{qid}/attempt',json={'answer':'原答案','notes':'原笔记','draft':'[[{"x":20,"y":30}]]'})
    attempt=client.get(f'/api/questions/{qid}').json()['attempt']
    assert client.get(f'/api/questions/{qid}/annotations').json()=={'version':0,'strokes':[],'updated_at':None}
    result=client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[stroke()]})
    assert result.status_code==200 and result.json()['version']==1
    assert client.get(f'/api/questions/{qid}/annotations').json()['strokes']==[stroke()]
    assert client.get(f'/api/questions/{qid}').json()['attempt']==attempt
    assert client.get('/api/files/annotation.png').content==original
    assert client.get('/api/practice/recent').json()[0]['id']==qid
    archive=zipfile.ZipFile(io.BytesIO(client.get('/api/backup').content))
    restored=sqlite3.connect(':memory:');restored.deserialize(archive.read('mathmaster.db'))
    assert json.loads(restored.execute('SELECT strokes FROM question_annotations WHERE question_id=?',(qid,)).fetchone()[0])==[stroke()]
    restored.close()


def test_annotations_are_personal_and_conflicts_do_not_overwrite(client):
    qid=create(client)
    guest=client.post('/api/users',json={'name':'标注访客'}).json()['id'];headers={'X-MathMaster-User':guest}
    assert client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[stroke()]}).status_code==200
    assert client.get(f'/api/questions/{qid}/annotations',headers=headers).json()['strokes']==[]
    guest_stroke={**stroke('guest-stroke'),'color':'#4dabf7'}
    assert client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[guest_stroke]},headers=headers).status_code==200
    assert client.get(f'/api/questions/{qid}/annotations').json()['strokes']==[stroke()]
    assert client.get(f'/api/questions/{qid}/annotations',headers=headers).json()['strokes']==[guest_stroke]
    destination=create(client)
    assert client.post(f'/api/questions/{destination}/merge',json={'other_id':qid}).status_code==409
    conflict=client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[]})
    assert conflict.status_code==409
    assert client.get(f'/api/questions/{qid}/annotations').json()['strokes']==[stroke()]
    assert client.put(f'/api/questions/{qid}/annotations',json={'version':1,'strokes':[]}).status_code==200
    assert client.get(f'/api/questions/{qid}/annotations').json()['strokes']==[]
    assert client.post(f'/api/questions/{destination}/merge',json={'other_id':qid}).status_code==409
    assert client.get(f'/api/questions/{qid}/annotations',headers=headers).json()['strokes']==[guest_stroke]


def test_annotation_validation_and_missing_questions(client):
    qid=create(client)
    for invalid in [{**stroke(),'width':31},{**stroke(),'points':[{'x':1.1,'y':.5}]},{**stroke(),'color':'url(evil)'},{**stroke(),'points':[]}]:
        assert client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[invalid]}).status_code==422
    assert client.put(f'/api/questions/{qid}/annotations',json={'version':0,'strokes':[stroke(),stroke()]}).status_code==422
    assert client.get('/api/questions/missing/annotations').status_code==404
    assert client.put('/api/questions/missing/annotations',json={'version':0,'strokes':[]}).status_code==404
    assert client.get(f'/api/questions/{qid}/annotations').json()['version']==0
