"""Install an offline, reviewed import plan. Run with native Windows Python for live data.
Reruns skip every existing question, preserving edits and learner history. All new knowledge
is installed in the same transaction as questions, before automatic vector workers see it.
"""
import argparse,collections,json,os,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import db,grading
from backend.ai import knowledge as k,vectors as v,profiles
LEARNER_TABLES=['attempts','history','note_calculations','answer_submissions','grade_batches','exam_runs','ai_sessions','ai_events','ai_observations']

def records(c):
 names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 return {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in LEARNER_TABLES if t in names}

def install(plan):
 ids=[q['id'] for q in plan['questions']]
 if len(ids)!=len(set(ids)):raise ValueError('重复题目 ID')
 for q in plan['questions']:
  if q['subject']!='数学二':raise ValueError('本次仅允许数学二')
  k.Analysis.model_validate(q['knowledge'])
  if not q['images'] or len(q['images'])>5:raise ValueError('请检查拆题 '+q['id'])
  for name in q['images']+q['spec'].get('reference_images',[]):
   path=(db.DATA/'uploads'/name).resolve()
   if not path.is_relative_to((db.DATA/'uploads').resolve()) or not path.is_file():raise ValueError('缺少原图 '+name)
 with db.connection() as c:
  before=records(c);c.execute('BEGIN IMMEDIATE');created=[];preserved=0;batch_time=k.now()
  for p in plan['papers']:
   c.execute('INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?)',(p['id'],p['title'],p['subject'],p['filename'],k.now(),k.dump(p['warnings'])))
  for q in plan['questions']:
   if c.execute('SELECT 1 FROM questions WHERE id=?',(q['id'],)).fetchone():preserved+=1;continue
   c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',(q['id'],q['paper_id'],q['number'],q['text'],k.dump(q['images']),q['reference_answer'],q['subject'],int(q['confirmed']),batch_time))
   c.execute('INSERT INTO question_grading VALUES(?,?)',(q['id'],k.dump(q['spec'])))
   payload=k.Analysis.model_validate(q['knowledge'])
   c.execute('INSERT INTO question_knowledge VALUES(?,?,?,?,?,?,?)',(q['id'],k.fingerprint(q),k.VERSION,payload.model_dump_json(),'本地 PDF 目录及关键词知识索引；原书解析关联；OCR 公式待核对','local-layout-ocr-v1',k.now()))
   created.append(q['id'])
  after=records(c)
  assert before==after,'导入不得修改学习记录'
 return {'created':len(created),'preserved_existing':preserved,'ids':ids,'learner_records':after,'linked_solutions':sum(bool(q['spec'].get('reference_images')) for q in plan['questions'])}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--plan',default=str(ROOT/'artifacts/new-pdfs/import-plan.json'));parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 plan=json.loads(Path(args.plan).read_text(encoding='utf-8'))
 if not args.apply:print(json.dumps({'papers':len(plan['papers']),'questions':len(plan['questions']),'issues':len(plan['issues']),'mode':'dry_run'},ensure_ascii=False));return
 if os.name!='nt':raise SystemExit('实时 Windows 题库必须由原生 Windows Python 写入，避免跨系统 WAL 锁冲突。')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S');backup=ROOT/'artifacts/new-pdfs'/f'mathmaster-before-import-{stamp}.db'
 with db.connection() as source:
  target=sqlite3.connect(backup);source.backup(target);target.close()
 result=install(plan);result['backup']=str(backup);print(json.dumps({k:v for k,v in result.items() if k!='ids'},ensure_ascii=False),flush=True)
 profile=profiles.selected('embedding')
 if profile.protocol!='local_bge':raise SystemExit('题目及知识已导入；当前向量配置非本地模型，本次未批量调用收费 API。')
 result['embedding']=v.index_questions(v.all_questions(ids=result['ids']),profile=profile,progress=lambda n:print('indexed',n,flush=True))
 result['model_calls']=0;result['local_only']=True;result['by_paper']=dict(collections.Counter(q['paper_id'] for q in plan['questions']))
 Path(args.plan).with_name(Path(args.plan).stem.replace('import-plan','import-result')+'.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k not in ('ids','by_paper')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
