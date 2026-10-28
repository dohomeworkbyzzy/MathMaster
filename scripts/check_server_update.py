"""Native frozen old-to-new upgrade, persistence, integrity and rollback checks."""
import argparse
import ctypes
import importlib.util
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('server_updater', ROOT / 'packaging/windows/server_updater.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, default=ROOT / 'artifacts/master')
    parser.add_argument('--updater', type=Path, default=ROOT / 'artifacts/master-update.exe')
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Run with native Windows Python.')
    env = {**os.environ, 'PATH': os.environ['SystemRoot'] + '\\System32', 'PYTHONUTF8': '1'}
    (ROOT / '.test-data').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='frozen update ', dir=ROOT / '.test-data') as temp:
        root = Path(temp) / 'portable server'
        root.mkdir()
        shutil.copy2(args.baseline / 'master.exe', root / 'master.exe')
        shutil.copytree(args.baseline / '_internal', root / '_internal')
        (root / 'config').mkdir()
        marker = b'private-local-setting-preserved'
        (root / 'config/preserved.txt').write_bytes(marker)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config = json.dumps({'host': '127.0.0.1', 'port': port, 'public_origins': [], 'background_indexing': False}).encode()
        (root / 'config.json').write_bytes(config)
        base = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, body=None, user=None, method=None):
            headers = {'Content-Type': 'application/json'}
            if user:
                headers['X-MathMaster-User'] = user
            data = json.dumps(body).encode() if body is not None else None
            with opener.open(urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw
        def wait_start():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if request('/api/health')['status'] == 'ok':
                        return
                except (OSError, ValueError):
                    pass
                time.sleep(.25)
            raise AssertionError((root / 'logs/server.log').read_text(encoding='utf-8', errors='replace')[-4000:])
        def start():
            process = subprocess.Popen([str(root / 'master.exe'), '--root', str(root)], env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            wait_start()
            return process
        def expect_status(code, callback):
            try:
                callback()
            except urllib.error.HTTPError as error:
                assert error.code == code
            else:
                raise AssertionError('Expected HTTP ' + str(code))
        process = None
        gui = None
        try:
            process = start()
            assert not any('annotations' in path for path in request('/openapi.json')['paths'])
            qid = request('/api/questions', {'text': 'Frozen upgrade fixture'})['id']
            attempt = {'answer': 'existing answer', 'notes': 'existing notes', 'draft': 'existing scratch'}
            request(f'/api/questions/{qid}/attempt', attempt, method='PUT')
            before = request('/api/questions/' + qid)['attempt']
            guest = request('/api/users', {'name': 'upgrade guest'})['id']
            request(f'/api/questions/{qid}/attempt', {'answer': 'guest answer'}, guest, 'PUT')
            (root / 'data/uploads/preserved.bin').write_bytes(b'original-upload')
            # Test the real frozen updater, with only System32 on PATH.
            result = subprocess.run([str(args.updater.resolve()), '--root', str(root), '--package', str(args.release.resolve())], env=env, timeout=240)
            assert result.returncode == 0, result.returncode
            process.wait(timeout=20)
            wait_start()
            assert '/api/questions/{qid}/annotations' in request('/openapi.json')['paths']
            if '/api/questions/{qid}/difficulty' in request('/openapi.json')['paths']:
                difficulty=request(f'/api/questions/{qid}/difficulty')
                assert difficulty['rating']['level'] is None
                request(f'/api/questions/{qid}/difficulty', {'level':4,'fingerprint':difficulty['rating']['fingerprint']},method='PUT')
                assert request(f'/api/questions/{qid}/difficulty')['rating']['level']==4
                assert request(f'/api/questions/{qid}/difficulty',user=guest)['rating']['level'] is None
            with zipfile.ZipFile(args.release) as archive:
                manifest = updater.read_manifest(archive)
            assert updater.digest(root / 'master.exe') == manifest['files']['master.exe']
            assert updater.digest(root / '_internal/dist/index.html') == manifest['files']['_internal/dist/index.html']
            assert request('/api/questions/' + qid)['attempt'] == before
            assert request('/api/questions/' + qid, user=guest)['attempt']['answer'] == 'guest answer'
            stroke = {'id': 'upgrade', 'image': 'fixture.png', 'tool': 'pen', 'color': '#ff6b6b',
                      'width': 3, 'points': [{'x': .2, 'y': .3}, {'x': .6, 'y': .3}]}
            request(f'/api/questions/{qid}/annotations', {'version': 0, 'strokes': [stroke]}, method='PUT')
            assert request(f'/api/questions/{qid}/annotations', user=guest)['strokes'] == []
            guest_stroke = {**stroke, 'id': 'guest', 'color': '#4dabf7'}
            request(f'/api/questions/{qid}/annotations', {'version': 0, 'strokes': [guest_stroke]}, guest, 'PUT')
            expect_status(409, lambda: request(f'/api/questions/{qid}/annotations', {'version': 0, 'strokes': []}, method='PUT'))
            updater.stop(root)
            process = start()
            assert request(f'/api/questions/{qid}/annotations')['strokes'] == [stroke]
            assert request(f'/api/questions/{qid}/annotations', user=guest)['strokes'] == [guest_stroke]
            if '/api/questions/{qid}/difficulty' in request('/openapi.json')['paths']:
                assert request(f'/api/questions/{qid}/difficulty')['rating']['level']==4
                assert request(f'/api/questions/{qid}/difficulty',user=guest)['rating']['level'] is None
            assert request('/api/questions/' + qid)['attempt'] == before
            assert (root / 'config.json').read_bytes() == config
            assert (root / 'config/preserved.txt').read_bytes() == marker
            assert (root / 'data/uploads/preserved.bin').read_bytes() == b'original-upload'
            backups = list((root / '.updates').iterdir())
            assert len(backups) == 1
            assert (backups[0] / 'data/mathmaster.db').is_file()
            # A corrupt archive is rejected while the current service stays up.
            corrupt = Path(temp) / 'corrupt.zip'
            bad_start = Path(temp) / 'bad-start.zip'
            with zipfile.ZipFile(args.release) as src, zipfile.ZipFile(corrupt, 'w', zipfile.ZIP_DEFLATED) as bad, zipfile.ZipFile(bad_start, 'w', zipfile.ZIP_DEFLATED) as invalid:
                bad_hash = {**manifest, 'files': {**manifest['files'], 'master.exe': '0' * 64}}
                bad.writestr('manifest.json', json.dumps(bad_hash))
                invalid.writestr('manifest.json', json.dumps({**manifest, 'required_routes': ['/api/this-update-must-fail']}))
                for entry in src.infolist():
                    if entry.filename != 'manifest.json':
                        data = src.read(entry.filename)
                        bad.writestr(entry.filename, data)
                        invalid.writestr(entry.filename, data)
            try:
                updater.apply_update(corrupt, root)
            except (ValueError, RuntimeError) as error:
                assert '校验失败' in str(error)
            else:
                raise AssertionError('Corrupt package accepted')
            assert process.poll() is None
            saved_exe = updater.digest(root / 'master.exe')
            # Failed API readiness must restore the runtime and restart it.
            try:
                updater.apply_update(bad_start, root)
            except RuntimeError as error:
                assert '已恢复旧程序' in str(error), str(error)
            else:
                raise AssertionError('Missing route was accepted')
            process.wait(timeout=20)
            wait_start()
            assert updater.digest(root / 'master.exe') == saved_exe
            assert request(f'/api/questions/{qid}/annotations')['strokes'] == [stroke]
            assert request('/api/questions/' + qid)['attempt'] == before
            # Launch the packaged GUI itself and check that its native window opens.
            gui = subprocess.Popen([str(args.updater.resolve())], env=env)
            user32 = ctypes.WinDLL('user32')
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = ctypes.c_void_p
            user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
            deadline = time.monotonic() + 40
            window = None
            while time.monotonic() < deadline:
                assert gui.poll() is None, 'Updater GUI exited before opening'
                window = user32.FindWindowW(None, 'master maintenance') or user32.FindWindowW(None, 'master update')
                if window:
                    break
                time.sleep(.25)
            assert window, 'Updater GUI did not open'
            user32.PostMessageW(window, 0x0010, 0, 0)
            gui.wait(timeout=20)
            assert gui.returncode == 0
            print(json.dumps({'frozen_upgrade': True, 'annotation_save_and_restart': True,
                              'personal_isolation': True, 'scratch_and_config_preserved': True,
                              'database_backup': True, 'corrupt_package_rejected_before_stop': True,
                              'failed_readiness_rollback': True, 'frozen_gui': True,
                              'requires_python_or_node': False}))
        finally:
            if updater.running(root):
                updater.stop(root)
            if process:
                process.wait(timeout=20)
            if gui and gui.poll() is None:
                gui.terminate()
                gui.wait(timeout=15)
            # Named stop events close just before Windows unloads native DLLs.
            # Wait for that final release before removing the isolated fixture.
            deadline = time.monotonic() + 15
            while root.exists():
                try:
                    shutil.rmtree(root)
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.25)


if __name__ == '__main__':
    main()
