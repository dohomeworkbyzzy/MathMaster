"""Repair missing point metadata from saved source pages without new LLM or embedding calls."""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import db,grading
from backend.ai import knowledge as k,vectors as v

def refresh():
    changed=0;reused=0
    with db.connection() as c:ids=[r[0] for r in c.execute("SELECT id FROM questions WHERE id LIKE 'real-math%'")]
    for qid in ids:
        with db.connection() as c:
            q=grading.question(c,qid)
            if not q['spec'].get('points_source'):continue
            row=c.execute('SELECT spec FROM question_grading WHERE question_id=?',(qid,)).fetchone()
            if row and json.loads(row[0]).get('points_source'):continue
        old=copy.deepcopy(q);old['spec']['max_points']=1;old['spec']['points_known']=False;old['spec'].pop('points_source',None)
        oldfp=k.fingerprint(old);analysis=k.get(old)
        if analysis:
            payload={key:value for key,value in analysis.items() if key in k.Analysis.model_fields}
            payload['rubric']='按原题明确标注的分值与参考解析评分；没有分项细则时为参考估分。'
            k.put(q,payload,analysis['source'],analysis['model_id']);reused+=1
            with db.connection() as c:
                doc=v.document(q,payload)
                from backend.ai.cache import key
                c.execute('UPDATE question_embeddings SET fingerprint=? WHERE question_id=? AND fingerprint=? AND document_hash=?',
                          (k.fingerprint(q),qid,oldfp,key(doc['text'])))
        with db.connection() as c:c.execute('INSERT OR REPLACE INTO question_grading VALUES(?,?)',(qid,grading.dumps(q['spec'])))
        changed+=1
    return {'point_metadata_corrected':changed,'knowledge_reused':reused,'new_model_calls':0}

if __name__=='__main__':print(json.dumps(refresh(),ensure_ascii=False),flush=True)
