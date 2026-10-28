"""Native Windows incremental local import with a SQLite backup and learner-content preservation check."""
import argparse,hashlib,json,os,sqlite3,sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'packaging/windows'))
from backend import db
from backend.user_storage import PERSONAL_TABLES
import library_update as lib

def personal_fingerprints(c):
 names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
 result={}
 for name in names:
  if name not in PERSONAL_TABLES and not name.startswith('user_') and name!='users':continue
  safe=name.replace('"','""');h=hashlib.sha256()
  for row in c.execute('SELECT * FROM "'+safe+'" ORDER BY rowid'):h.update(repr(tuple(row)).encode('utf-8'))
  result[name]=h.hexdigest()
 return result

def main():
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);a=p.parse_args()
 if os.name!='nt':raise SystemExit('Live Windows SQLite must be written by native Windows Python.')
 target=db.DATA/'mathmaster.db'
 if not target.is_file():raise SystemExit('Existing local question bank not found.')
 plan=json.loads(a.plan.read_text(encoding='utf-8'));files={'plan.json':lib.digest(a.plan)}
 assets={p['filename'] for p in plan['papers'] if p['filename']}
 for q in plan['questions']:assets.update(q['images']+q['spec'].get('reference_images',[]))
 for name in assets:lib.safe_name(name);files['uploads/'+name]=lib.digest(db.DATA/'uploads'/name)
 lib.validate_plan(plan,files)
 version='local-'+lib.digest(a.plan)[:16];manifest={'version':version,'files':files}
 out=ROOT/'artifacts/408-workbooks';backups=out/'backups';backups.mkdir(parents=True,exist_ok=True);stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
 backup=backups/f'before-{stamp}.db'
 with closing(sqlite3.connect(target,timeout=30)) as c:
  before=personal_fingerprints(c)
  with closing(sqlite3.connect(backup)) as snapshot:c.backup(snapshot)
 result=lib.install_plan(db.DATA,db.DATA,manifest,plan)
 with closing(sqlite3.connect(target,timeout=30)) as c:
  after=personal_fingerprints(c);assert before==after,'Learner records changed during import'
  assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert c.execute('PRAGMA foreign_key_check').fetchone() is None
 result.update(backup=str(backup),learner_content_preserved=True,integrity='ok')
 (out/f'local-import-{stamp}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
