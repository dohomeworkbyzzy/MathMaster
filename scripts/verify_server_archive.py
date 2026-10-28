"""Verify every archived file, then boot the migrated copy after extraction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
import urllib.request
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    archive=args.archive.resolve();destination=args.destination.resolve()
    if destination.exists():raise SystemExit('Use an empty verification destination.')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('master/manifest.json'))
        for name,expected in manifest.items():
            with z.open('master/'+name) as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            assert actual==expected,name
        assert set(z.namelist())=={'master/'+p for p in manifest}|{'master/manifest.json'}
        z.extractall(destination)
    root=destination/'master';exe=root/'master.exe'
    with sqlite3.connect(root/'data/mathmaster.db') as c:
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('papers','questions','users','attempts','history','ai_sessions','answer_submissions')}
        qid,images=c.execute("SELECT id,images FROM questions WHERE images!='[]' LIMIT 1").fetchone()
        image=json.loads(images)[0]
    # Use a temporary loopback port in the extracted validation copy only.
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    original=(root/'config.json').read_bytes()
    cfg=json.loads(original);assert cfg['port']==8509 and cfg['public_origins']==['http://39.129.11.4:8509']
    (root/'config.json').write_text(json.dumps({**cfg,'host':'127.0.0.1','port':port,'background_indexing':False}),encoding='utf-8')
    env={**os.environ,'PATH':os.environ['SystemRoot']+'\\System32','PYTHONUTF8':'1'}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base='http://127.0.0.1:'+str(port)
    def get(path,headers=None):
        with opener.open(urllib.request.Request(base+path,headers=headers or {}),timeout=30) as r:
            raw=r.read();return json.loads(raw) if 'application/json' in r.headers.get('content-type','') else raw
    with (destination/'validation.log').open('wb') as log:
        process=subprocess.Popen([str(exe)],cwd=root,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(150):
                if process.poll() is not None:raise AssertionError('Extracted executable exited early.')
                try:
                    if get('/api/health')['status']=='ok':break
                except (OSError,ValueError):time.sleep(.2)
            else:raise AssertionError('Extracted server did not start.')
            registry=get('/api/users')
            assert registry['current_user']=='zzy' and registry['remaining']==3-counts['users']
            stats=get('/api/stats');assert stats['questions']==counts['questions'] and stats['papers']==counts['papers']
            with (root/'config/providers.json').open(encoding='utf-8') as file:stored=json.load(file)
            profiles=get('/api/ai/profiles',{'Host':'39.129.11.4:8509'})
            assert len(profiles['profiles'])==len(stored['profiles'])
            assert all(set(p)=={'id','kind','model_id'} for p in profiles['profiles'])
            get('/api/questions/'+qid);assert get('/api/files/'+image)
            print(json.dumps({'zip_entries_verified':len(manifest)+1,'extracted_startup':True,'migrated_record_counts':counts,
                              'private_model_configuration_preserved':True,'public_url':'http://39.129.11.4:8509',
                              'referenced_image_served':True}))
        finally:
            if process.poll() is None:
                subprocess.run([str(exe),'--stop'],cwd=root,env=env,capture_output=True,timeout=15,check=True)
                process.wait(timeout=30)
            assert process.returncode==0
            (root/'config.json').write_bytes(original)


if __name__=='__main__':main()
