"""Native Windows acceptance: frozen data imports, replay, backups, persistence and rollback."""
from contextlib import closing
import argparse,ctypes,hashlib,importlib.util,json,os,shutil,socket,sqlite3,subprocess,sys,tempfile,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'packaging/windows'))
import server_updater as updater
import library_update as lib

def main():
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--sample',type=int,default=0);p.add_argument('--program-release',type=Path);p.add_argument('--package',type=Path,required=True);p.add_argument('--runtime',type=Path,default=ROOT/'artifacts/maintenance-build/master');a=p.parse_args()
 if os.name!='nt':raise SystemExit('Run with native Windows Python.')
 with zipfile.ZipFile(a.package) as z:manifest=lib.read_manifest(z);plan=json.loads(z.read('plan.json'))
 env={**os.environ,'PATH':os.environ['SystemRoot']+'\\System32','PYTHONUTF8':'1'}
 with tempfile.TemporaryDirectory(prefix='library maintenance ',dir=ROOT/'.test-data') as tmp:
  root=Path(tmp)/'portable server';root.mkdir();shutil.copy2(a.runtime/'master.exe',root/'master.exe');shutil.copytree(a.runtime/'_internal',root/'_internal')
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  if manifest.get('required_program_version'):
   if not a.program_release:raise ValueError('Provide the matching program release for this data package.')
   with zipfile.ZipFile(a.program_release) as z:release=updater.read_manifest(z)
   assert release['version']==manifest['required_program_version']
   assert updater.digest(root/'master.exe')==release['files']['master.exe']
   assert updater.digest(root/'_internal/dist/index.html')==release['files']['_internal/dist/index.html']
   (root/'release.json').write_text(json.dumps({k:v for k,v in release.items() if k!='files'}),encoding='utf-8')
  config=json.dumps({'host':'127.0.0.1','port':port,'public_origins':[],'background_indexing':False}).encode();(root/'config.json').write_bytes(config)
  (root/'config').mkdir();(root/'config/preserved.txt').write_text('private config marker',encoding='utf-8')
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{port}'
  def req(path,body=None,user=None,method=None):
   headers={'Content-Type':'application/json'}
   if user:headers['X-MathMaster-User']=user
   with opener.open(urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method),timeout=20) as r:
    raw=r.read();return json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else raw
  def wait_start():
   end=time.monotonic()+75
   while time.monotonic()<end:
    try:
     if req('/api/health')['status']=='ok':return
    except (OSError,ValueError):pass
    time.sleep(.3)
   raise AssertionError('Service did not start')
  def invoke():
   completed=subprocess.run([str(ROOT/'artifacts/master-maintenance.exe'),'--root',str(root),'--package',str(a.package.resolve())],env=env,timeout=240)
   assert completed.returncode==0,completed.returncode
   wait_start()
  try:
   process=updater.launch(root);wait_start();old=req('/api/questions',{'text':'Existing learner fixture'})['id'];req(f'/api/questions/{old}/attempt',{'answer':'my answer','draft':'my draft','notes':'my notes'},method='PUT')
   guest=req('/api/users',{'name':'maintenance guest'})['id'];req(f'/api/questions/{old}/attempt',{'answer':'guest answer'},guest,'PUT')
   old_attempt=req('/api/questions/'+old)['attempt'];old_guest=req('/api/questions/'+old,user=guest)['attempt'];runtime_hash=updater.digest(root/'master.exe')
   invoke();assert (root/'config.json').read_bytes()==config;assert updater.digest(root/'master.exe')==runtime_hash
   sample=plan['questions'] if not a.sample else [plan['questions'][i] for i in sorted({0,len(plan['questions'])-1,*range(0,len(plan['questions']),max(1,len(plan['questions'])//a.sample))})]
   for q in sample:
    actual=req('/api/questions/'+q['id']);assert actual['reference_answer']==q['reference_answer'];assert actual['text']==q['text']
    for image in q['images']:assert hashlib.sha256(req('/api/files/'+image)).hexdigest()==manifest['files']['uploads/'+image]
   assert req('/api/questions/'+old)['attempt']==old_attempt
   assert req('/api/questions/'+old,user=guest)['attempt']==old_guest
   # User corrections survive a second application of the identical package.
   q0=plan['questions'][0];req('/api/questions/'+q0['id'],{'text':q0['text'],'number':q0['number'],'subject':'408','reference_answer':'user corrected answer','confirmed':False},method='PUT')
   invoke();assert req('/api/questions/'+q0['id'])['reference_answer']=='user corrected answer'
   with closing(sqlite3.connect(root/'data/mathmaster.db')) as c:
    assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert c.execute('SELECT count(*) FROM questions').fetchone()[0]==len(plan['questions'])+1
   # Simulate a startup-check error after a committed data import; recover the snapshot.
   prior=updater.check_started
   def fail(*args,**kwargs):raise RuntimeError('acceptance injected startup failure')
   updater.check_started=fail
   try:
    try:updater.apply_library(a.package.resolve(),root,lambda t:None)
    except RuntimeError as error:assert 'acceptance injected' in str(error)
    else:raise AssertionError('Failure was not reported')
   finally:updater.check_started=prior
   wait_start();assert req('/api/questions/'+old)['attempt']==old_attempt;assert req('/api/questions/'+q0['id'])['reference_answer']=='user corrected answer'
   assert len(list((root/'.updates').glob('*/data/mathmaster.db')))==3
   print(json.dumps({'frozen_data_import':True,'questions':len(plan['questions']),'images_and_answers_served':True,'repeat_preserves_corrections':True,'both_users_preserved':True,'runtime_and_config_preserved':True,'snapshot_backup':True,'failed_readiness_restores_database':True,'integrity':'ok','requires_python_or_node':False}),flush=True)
  finally:
   if updater.running(root):updater.stop(root)
   deadline=time.monotonic()+15
   while root.exists():
    try:shutil.rmtree(root)
    except PermissionError:
     if time.monotonic()>=deadline:raise
     time.sleep(.3)
if __name__=='__main__':main()
