"""Exercise the real frozen EXE without relying on Python/Node in its PATH."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import io


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable')
    parser.add_argument('--headless-only', action='store_true', help='CI without an interactive desktop')
    args = parser.parse_args()
    exe = Path(args.executable).resolve()
    root = Path(__file__).resolve().parents[1]
    assert os.name == 'nt' and exe.is_file()
    with tempfile.TemporaryDirectory(prefix='MathMaster-acceptance-') as tmp:
        data = Path(tmp)/'data'
        env = {**os.environ, 'MATHMASTER_DATA': str(data), 'MATHMASTER_PORT': '8875',
               'PYTHONUTF8': '1', 'PATH': os.environ['SystemRoot']+'\\System32'}
        flags = subprocess.CREATE_NO_WINDOW
        native = subprocess.run([str(exe), '--touchpad-worker', '--probe'], env=env, capture_output=True, timeout=15)
        assert native.returncode == 0, native.stderr.decode(errors='replace')
        assert 'available' in json.loads(native.stdout)
        url = None
        process = None

        def request(path, body=None, raw=None, content_type=None):
            payload = json.dumps(body).encode() if body is not None else raw
            req = urllib.request.Request(url+path, data=payload,
                  headers={'Content-Type': content_type or 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                content = r.read()
                return content if raw is not None else json.loads(content)

        def start(extra_env=None, tray=False):
            nonlocal process, url
            active_env = {**env, **(extra_env or {})}
            process = subprocess.Popen([str(exe), '--no-browser', *([] if tray else ['--headless'])],
                                       env=active_env, creationflags=flags)
            for _ in range(200):
                if process.poll() is not None:
                    logs = Path(tmp)/'logs'
                    raise AssertionError('Packaged app exited: '+str([p.read_text(encoding='utf-8')[-3000:] for p in logs.glob('*.log')]))
                states = list(Path(tmp).glob('runtime-*.json'))
                if states:
                    url = json.loads(states[0].read_text())['url']
                    try:
                        if request('/api/health')['local']:
                            return
                    except (OSError, ValueError):
                        pass
                time.sleep(.1)
            raise AssertionError('Packaged app did not start')

        def stop():
            if process and process.poll() is None:
                subprocess.run([str(exe), '--quit'], env=env, creationflags=flags, timeout=10, check=True)
                process.wait(timeout=15)
                assert process.returncode == 0

        try:
            start({'MATHMASTER_TIMEOUT': '0.01'})
            for _ in range(3):
                try:
                    request('/api/math/integrate', {'expression': 'x*exp(x)'})
                except urllib.error.HTTPError as error:
                    assert error.code == 422
                    assert '超时' in json.loads(error.read())['detail']
                else:
                    raise AssertionError('Timeout must terminate a frozen worker')
            stop()
            start(tray=not args.headless_only)
            with urllib.request.urlopen(url, timeout=5) as r:
                assert '考研数学'.encode() in r.read()
            checks = []
            for endpoint, body, expected in [
                ('integrate', {'expression': 'x*exp(x)'}, '(x - 1)*exp(x) + C'),
                ('integrate', {'expression': 'x^2', 'lower': '0', 'upper': '1'}, '1/3'),
                ('differentiate', {'expression': 'sin(x^2)'}, '2*x*cos(x**2)'),
                ('matrix', {'matrix': [['0','1'],['2','3']], 'action': 'inverse'}, 'Matrix([[-3/2, 1/2], [1, 0]])'),
            ]:
                result = request('/api/math/'+endpoint, body)
                assert result['verified'] and result['exact_result'] == expected, result
                assert result['steps'] and all(step['verified'] for step in result['steps'])
                checks.append(endpoint)
            q = request('/api/questions', {'text': '安装版测试题：$x^2$', 'number':'1', 'confirmed':True})
            notes = {'notes':'安装版验收笔记', 'draft':'[[{"x":10,"y":20},{"x":30,"y":40}]]', 'expected_updated_at':None}
            req = urllib.request.Request(url+'/api/questions/'+q['id']+'/attempt', data=json.dumps(notes).encode(),
                   method='PUT', headers={'Content-Type':'application/json'})
            urllib.request.urlopen(req, timeout=5).close()
            for ext in ('pdf','docx'):
                boundary = 'MathMasterAcceptanceBoundary'
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nInstaller fixture\r\n'
                        f'--{boundary}\r\nContent-Disposition: form-data; name="subject"\r\n\r\n数学一\r\n'
                        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="exam.{ext}"\r\n'
                        'Content-Type: application/octet-stream\r\n\r\n').encode()
                body += (root/'tests/fixtures'/('exam.'+ext)).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
                result = json.loads(request('/api/papers/import', raw=body, content_type='multipart/form-data; boundary='+boundary))
                assert result['count'] == 2, result
            with urllib.request.urlopen(url+'/api/backup', timeout=10) as r:
                with zipfile.ZipFile(io.BytesIO(r.read())) as z:
                    assert 'mathmaster.db' in z.namelist() and z.testzip() is None
            second = subprocess.run([str(exe), '--no-browser'], env=env, creationflags=flags, timeout=20)
            assert second.returncode == 0 and process.poll() is None
            stop()
            start()
            assert request('/api/questions/'+q['id'])['attempt']['notes'] == notes['notes']
            assert len(request('/api/math/history')) == 4
            stop()
            assert (data/'mathmaster.db').exists()
            print(json.dumps({'frozen_executable':str(exe), 'checks':checks,
                'native_probe':True, 'timeout_recovery':True, 'pdf_docx_import':True,
                'notes_restart_backup':True, 'single_instance':True, 'tray_verified':not args.headless_only,
                'external_python_node_required':False}, ensure_ascii=True))
        finally:
            if process and process.poll() is None:
                stop()


if __name__ == '__main__':
    main()
