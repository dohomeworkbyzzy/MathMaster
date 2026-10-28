"""Read-only export of existing public 408 reference questions for answer consistency checks."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import db
out=ROOT/'artifacts/408-workbooks/existing-references.json'
with db.connection() as c:
 rows=c.execute("SELECT q.id,q.text,q.reference_answer,g.spec FROM questions q JOIN question_grading g ON g.question_id=q.id WHERE q.id LIKE 'real-408-%' ORDER BY q.id").fetchall()
 values=[]
 for row in rows:
  spec=json.loads(row['spec'])
  if spec.get('answer_key') not in ('A','B','C','D'):continue
  values.append({'id':row['id'],'text':row['text'],'answer_key':spec['answer_key'],'reference_answer':row['reference_answer'],'source':spec.get('source','')})
out.write_text(json.dumps(values,ensure_ascii=False),encoding='utf-8');print('Existing MCQ references',len(values))
