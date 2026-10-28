"""Exercise real incremental imports, replay, failures and unsafe packages."""
import hashlib,importlib.util,json,sqlite3,sys,zipfile
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'packaging/windows'))
import library_update as lib

def fixture(tmp_path):
 data=tmp_path/'data';data.mkdir();stage=tmp_path/'stage';stage.mkdir()
 with sqlite3.connect(data/'mathmaster.db') as c:
  c.executescript('''CREATE TABLE papers(id TEXT PRIMARY KEY,title TEXT,subject TEXT,filename TEXT,created_at TEXT,warnings TEXT);
  CREATE TABLE questions(id TEXT PRIMARY KEY,paper_id TEXT REFERENCES papers(id),number TEXT,text TEXT,images TEXT,reference_answer TEXT,subject TEXT,confirmed INTEGER,created_at TEXT);
  CREATE TABLE attempts(question_id TEXT PRIMARY KEY REFERENCES questions(id),answer TEXT);
  CREATE TABLE user_abcdef__attempts(question_id TEXT,answer TEXT);
  INSERT INTO papers VALUES('existing','Original','408','','','[]');
  INSERT INTO questions VALUES('old','existing','1','edited','[]','C','408',1,'');
  INSERT INTO attempts VALUES('old','my answer');
  INSERT INTO user_abcdef__attempts VALUES('old','other user answer');''')
 (stage/'uploads').mkdir();(stage/'uploads/q.jpg').write_bytes(b'original question image')
 plan={'papers':[{'id':'new','title':'New','subject':'408','filename':''}],
       'questions':[{'id':'q1','paper_id':'new','number':'1','text':'Question','images':['q.jpg'],'reference_answer':'AI 生成，待核对：A','subject':'408','spec':{'kind':'mcq','max_points':1,'answer_key':'A','answer_origin':'ai_generated'}}]}
 files={'plan.json':'0'*64,'uploads/q.jpg':lib.digest(stage/'uploads/q.jpg')};manifest={'version':'test','files':files}
 return data,stage,manifest,plan

def test_import_replay_preserves_edits_and_all_users(tmp_path):
 data,stage,m,plan=fixture(tmp_path);lib.validate_plan(plan,m['files'])
 assert lib.install_plan(data,stage,m,plan)['created']==1
 with sqlite3.connect(data/'mathmaster.db') as c:c.execute("UPDATE questions SET text='user edit',reference_answer='B' WHERE id='q1'")
 result=lib.install_plan(data,stage,m,plan)
 assert result['created']==0 and result['preserved_existing']==1
 with sqlite3.connect(data/'mathmaster.db') as c:
  assert c.execute("SELECT text,reference_answer FROM questions WHERE id='q1'").fetchone()==('user edit','B')
  assert c.execute('SELECT answer FROM attempts').fetchone()[0]=='my answer'
  assert c.execute('SELECT answer FROM user_abcdef__attempts').fetchone()[0]=='other user answer'
  assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
 assert (data/'uploads/q.jpg').read_bytes()==b'original question image'

def test_asset_conflict_leaves_bank_unchanged(tmp_path):
 data,stage,m,plan=fixture(tmp_path);(data/'uploads').mkdir();(data/'uploads/q.jpg').write_bytes(b'edited asset')
 with pytest.raises(ValueError,match='同名附件'):lib.install_plan(data,stage,m,plan)
 with sqlite3.connect(data/'mathmaster.db') as c:assert c.execute('SELECT count(*) FROM questions').fetchone()[0]==1

def test_sql_failure_rolls_back_papers_and_questions(tmp_path):
 data,stage,m,plan=fixture(tmp_path)
 plan['questions'].append({**plan['questions'][0],'id':'q2','paper_id':'missing'})
 with pytest.raises(sqlite3.IntegrityError):lib.install_plan(data,stage,m,plan)
 with sqlite3.connect(data/'mathmaster.db') as c:
  assert c.execute('SELECT count(*) FROM papers').fetchone()[0]==1
  assert c.execute('SELECT count(*) FROM questions').fetchone()[0]==1
 assert not (data/'uploads/q.jpg').exists()

@pytest.mark.parametrize('name',['../q.png','/q.png','x/../q.png','C:/q.png','x\\q.png','CON.png','x./q.png'])
def test_unsafe_paths_rejected(name):
 with pytest.raises(ValueError):lib.safe_name(name)

def test_missing_attachment_rejected(tmp_path):
 data,stage,m,plan=fixture(tmp_path)
 with pytest.raises(ValueError,match='缺少'):lib.validate_plan(plan,{'plan.json':'0'*64})

def test_corruption_rejected_before_import(tmp_path):
 data,stage,m,plan=fixture(tmp_path);package=tmp_path/'library.zip'
 contents={'plan.json':json.dumps(plan).encode(),'uploads/q.jpg':b'image'}
 manifest={'format':1,'product':lib.PRODUCT,'version':'test','files':{n:hashlib.sha256(v).hexdigest() for n,v in contents.items()}}
 manifest['files']['uploads/q.jpg']='0'*64
 with zipfile.ZipFile(package,'w') as z:
  z.writestr('manifest.json',json.dumps(manifest))
  for n,v in contents.items():z.writestr(n,v)
 with pytest.raises(ValueError,match='校验失败'):lib.extract_verified(package,tmp_path/'extract')
 with sqlite3.connect(data/'mathmaster.db') as c:assert c.execute('SELECT count(*) FROM questions').fetchone()[0]==1

def test_fill_only_missing_answer_on_unchanged_question(tmp_path):
 data,stage,m,plan=fixture(tmp_path)
 plan['questions'][0]['reference_answer']='';plan['questions'][0]['spec']['answer_key']=''
 lib.install_plan(data,stage,m,plan)
 plan['questions'][0]['reference_answer']='AI 生成、待核对：A';plan['questions'][0]['spec']['answer_key']='A'
 assert lib.install_plan(data,stage,m,plan)['filled_answers']==1
 assert lib.install_plan(data,stage,m,plan)['filled_answers']==0

def test_edited_question_never_gets_incoming_answer(tmp_path):
 data,stage,m,plan=fixture(tmp_path)
 answer=plan['questions'][0]['reference_answer'];plan['questions'][0]['reference_answer']='';plan['questions'][0]['spec']['answer_key']=''
 lib.install_plan(data,stage,m,plan)
 with sqlite3.connect(data/'mathmaster.db') as c:c.execute("UPDATE questions SET text='different question' WHERE id='q1'")
 plan['questions'][0]['reference_answer']=answer;plan['questions'][0]['spec']['answer_key']='A'
 assert lib.install_plan(data,stage,m,plan)['filled_answers']==0
