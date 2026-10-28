import json
import pytest
from backend import db,grading
from backend.ai import knowledge as k,vectors as v,provider,cache
from scripts import import_2026_answers as importer

def test_import_keeps_user_answers_and_reuses_knowledge_vectors_without_model(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    db.init_db();grading.init();k.init();v.init()
    monkeypatch.setattr(v,'_worker',None)
    def unexpected(*a,**kw):pytest.fail('补参考答案无需调用模型')
    monkeypatch.setattr(provider,'request_profile',unexpected)
    monkeypatch.setattr(v,'embed',unexpected)
    for subject in importer.ANSWERS:
        for n in range(1,23):
            qid=f'real-{subject}-2026-q{n:02}'
            ref='我已核对的答案' if subject=='math1' and n==1 else ''
            with db.connection() as c:
                c.execute('INSERT INTO questions VALUES(?,NULL,?,?,?, ?,?,1,?)',(qid,str(n),'测试题','[]',ref,'数学二',k.now()))
                spec={'kind':'mcq' if n<=10 else 'fill' if n<=16 else 'subjective','max_points':5,'solution':ref,'answer_key':ref}
                c.execute('INSERT INTO question_grading VALUES(?,?)',(qid,grading.dumps(spec)))
    qid='real-math2-2026-q01'
    with db.connection() as c:old=k.bank_question(c,qid)
    payload={'question_id':qid,'question_text':'测试题','uncertain':False,'has_diagram':False,'topic':'极限',
             'methods':[{'name':'泰勒展开','first_question':'先展开哪一项？','checkpoints':['核对阶数']}],
             'private_solution':'旧解析','problem':{}}
    k.put(old,payload,'fixture')
    doc=v.document(old,payload)
    with db.connection() as c:
        c.execute('INSERT INTO question_embeddings VALUES(?,?,?,?,?,?,?,?,?,?)',(qid,'fixture-space',k.fingerprint(old),cache.key(doc['text']),2,b'unchanged-vector',doc['topic'],json.dumps(doc['concepts']),doc['text'],k.now()))
        c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',(qid,'B','学习笔记','[]','作答中',0,k.now()))
        learner=tuple(c.execute('SELECT * FROM attempts').fetchone())
        vector=tuple(c.execute('SELECT * FROM question_embeddings').fetchone())
    report=importer.install()
    assert report['installed']==43 and report['preserved_existing']==1 and len(report['needs_source_review'])==2
    with db.connection() as c:
        assert c.execute('SELECT reference_answer FROM questions WHERE id=?',('real-math1-2026-q01',)).fetchone()[0]=='我已核对的答案'
        assert tuple(c.execute('SELECT * FROM attempts').fetchone())==learner
        current=k.bank_question(c,qid);updated=tuple(c.execute('SELECT * FROM question_embeddings').fetchone())
        assert updated[:2]+updated[3:]==vector[:2]+vector[3:] and updated[2]==k.fingerprint(current)!=vector[2]
        analysis=k.get(current);assert analysis['methods']==payload['methods'] and analysis['solution_basis']=='reference'
        assert c.execute('SELECT count(*) FROM question_knowledge WHERE question_id=?',(qid,)).fetchone()[0]==2
        assert current['spec']['answer_key']=='A' and current['spec']['solution']==current['reference_answer']
        assert grading.evaluate(current,{'answer':'A','reasoning':''})['score']==5
        fill=k.bank_question(c,'real-math2-2026-q14')
        assert grading.evaluate(fill,{'answer':'-2*pi','reasoning':''})['score']==5
        conflict=k.bank_question(c,'real-math2-2026-q07')
        assert grading.evaluate(conflict,{'answer':'D','reasoning':''})['status']=='pending'
    assert importer.install()['preserved_existing']==44
