"""Exercise the frozen server using a clean portable root and no Python in PATH."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    args=parser.parse_args()
    exe=args.executable.resolve()
    if os.name!='nt':raise SystemExit('Native Windows only.')
    project=Path(__file__).resolve().parents[1]
    env={**os.environ,'PATH':os.environ['SystemRoot']+'\\System32','PYTHONUTF8':'1'}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='master acceptance ') as tmp:
        root=Path(tmp)/'portable root';root.mkdir()
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        config={'host':'127.0.0.1','port':port,'public_origins':['http://39.129.11.4:8509'],'background_indexing':False}
        (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
        weights=project/'data/models/bge-small-zh-v1.5'
        if weights.is_dir():shutil.copytree(weights,root/'data/models/bge-small-zh-v1.5')
        url='http://127.0.0.1:'+str(port)
        def request(path,body=None,headers=None,raw=None,method=None):
            data=json.dumps(body).encode() if body is not None else raw
            hdr={'Content-Type':'application/json',**(headers or {})}
            with opener.open(urllib.request.Request(url+path,data=data,headers=hdr,method=method),timeout=60) as response:
                payload=response.read()
                return response.status,json.loads(payload) if 'application/json' in response.headers.get('content-type','') else payload
        log=(root/'acceptance.log').open('wb')
        process=None
        def start():
            nonlocal process
            process=subprocess.Popen([str(exe),'--root',str(root)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(150):
                if process.poll() is not None:raise AssertionError((root/'acceptance.log').read_text(encoding='utf-8',errors='replace')[-4000:])
                try:
                    if request('/api/health')[1]['status']=='ok':return
                except (OSError,ValueError):time.sleep(.2)
            raise AssertionError('Server did not start.')
        def stop():
            subprocess.run([str(exe),'--root',str(root),'--stop'],env=env,capture_output=True,check=True,timeout=15)
            process.wait(timeout=30);assert process.returncode==0
        try:
            start()
            assert request('/')[0]==200
            assert request('/api/users')[1]['remaining']==2
            duplicate=subprocess.run([str(exe),'--root',str(root)],env=env,capture_output=True,timeout=15)
            assert duplicate.returncode==0 and b'already running' in duplicate.stdout
            result=request('/api/math/differentiate',{'expression':'x^2'})[1]
            assert result['verified'] and result['exact_result']=='2*x',result
            if weights.is_dir():
                embedding=request('/api/ai/profiles/builtin-bge/test',{})[1]
                assert embedding['dimensions']==512,embedding
            pids=[]
            for model in ('portable-a','portable-b'):
                r=request('/api/ai/profiles',{'kind':'chat','provider_name':'hidden website','base_url':'https://fixture.invalid/v1','model_id':model,'api_key':'private-test-key','protocol':'openai_chat_completions'})[1]
                pids.append(next(p['id'] for p in r['profiles'] if p['model_id']==model))
            request('/api/ai/profiles/'+pids[0]+'/activate',{})
            qid=request('/api/questions',{'text':'Portable root isolation test'})[1]['id']
            request('/api/questions/'+qid+'/attempt',{'answer':'zzy-saved'},method='PUT')
            first=request('/api/users',{'name':'first'})[1]['id']
            request('/api/users',{'name':'second'})
            try:request('/api/users',{'name':'fourth'})
            except urllib.error.HTTPError as e:assert e.code==409
            else:raise AssertionError('User limit not enforced.')
            remote={'Host':'39.129.11.4:8509','Origin':'http://39.129.11.4:8509','X-MathMaster-User':first}
            switched=request('/api/ai/profiles/'+pids[1]+'/activate',{},headers=remote)[1]
            assert switched['active_chat']==pids[1] and all(set(p)=={'id','kind','model_id'} for p in switched['profiles'])
            assert request('/api/questions/'+qid,headers=remote)[1]['attempt']=={}
            request('/api/questions/'+qid+'/attempt',{'answer':'first-saved'},headers=remote,method='PUT')
            assert request('/api/questions/'+qid)[1]['attempt']['answer']=='zzy-saved'
            try:request('/api/ai/profiles',{},headers=remote)
            except urllib.error.HTTPError as e:assert e.code==403
            else:raise AssertionError('Remote configuration editing was allowed.')
            boundary='master-boundary'
            pdf=(project/'tests/fixtures/exam.pdf').read_bytes()
            multipart=(f'--{boundary}\r\nContent-Disposition: form-data; name="subject"\r\n\r\n数学一\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="exam.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode()+pdf+f'\r\n--{boundary}--\r\n'.encode()
            assert request('/api/papers/import',raw=multipart,headers={'Content-Type':'multipart/form-data; boundary='+boundary})[0]==200
            stop();start()
            assert request('/api/questions/'+qid,headers=remote)[1]['attempt']['answer']=='first-saved'
            assert request('/api/ai/provider',headers=remote)[1]['model_id']=='portable-b'
            stop()
            configure=subprocess.run([str(exe),'--root',str(root),'--configure','--url','http://39.129.11.4:8509'],env=env,capture_output=True,timeout=15)
            assert configure.returncode==0 and json.loads((root/'config.json').read_text())['port']==8509
            print(json.dumps({'frozen_server':True,'isolated_math_worker':True,'local_embedding':weights.is_dir(),
                              'pdf_import':True,'three_users':True,'personal_model_selection':True,'remote_redaction':True,
                              'restart_persistence':True,'stop_and_duplicate_start':True,'python_node_required':False}))
        finally:
            if process and process.poll() is None:
                try:stop()
                except Exception:process.kill();process.wait(timeout=10)
            log.close()


if __name__=='__main__':main()
