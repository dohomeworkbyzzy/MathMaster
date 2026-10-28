"""Build a state-free release ZIP and a double-click offline Windows updater."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / 'packaging/windows/server_updater.py'
spec = importlib.util.spec_from_file_location('server_updater', UPDATER)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-only', action='store_true', help='Build only the reusable program release ZIP.')
    parser.add_argument('--skip-build', action='store_true', help='Use an already rebuilt server runtime.')
    parser.add_argument('--runtime', type=Path, default=ROOT / 'artifacts/annotations-build/master')
    parser.add_argument('--output-name', default='master-update', choices=['master-update','master-difficulty-update','master-calculus-update'])
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Run with native Windows Python.')
    runtime = args.runtime.resolve()
    if not args.skip_build:
        # npm.cmd is a batch file; the Windows shell resolves it without PATH tricks.
        subprocess.run('npm run build', cwd=ROOT, shell=True, check=True)
        run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(runtime.parent),
             '--workpath', str(ROOT / '.tools/build-server-annotations'), 'packaging/windows/master.spec'])
    if not (runtime / 'master.exe').is_file() or not (runtime / '_internal/dist/index.html').is_file():
        raise SystemExit('Build the frozen master runtime first.')
    files = {'master.exe': updater.digest(runtime / 'master.exe')}
    for path in sorted((runtime / '_internal').rglob('*')):
        if path.is_file():
            files[path.relative_to(runtime).as_posix()] = updater.digest(path)
    signature = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]
    version = datetime.now(timezone.utc).strftime('%Y.%m.%d-%H%M%S-') + signature
    manifest = {'format': 1, 'product': updater.PRODUCT, 'version': version,
                'created_at': datetime.now(timezone.utc).isoformat(), 'platform': 'windows-x64',
                'required_routes': ['/api/questions/{qid}/annotations', '/api/questions/{qid}/difficulty', '/api/ai/sessions/{sid}/recommend'], 'files': files}
    work = ROOT / '.tools/update-payload'
    work.mkdir(parents=True, exist_ok=True)
    payload = work / 'payload.zip'
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in files:
            archive.write(runtime / name, name)
    with zipfile.ZipFile(payload) as archive:
        assert updater.read_manifest(archive)['version'] == version
        assert archive.testzip() is None
    release = ROOT / 'artifacts' / ('master-release-' + version + '.zip')
    import shutil
    shutil.copyfile(payload, release)
    if not args.package_only:
        run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
         '--name', args.output_name, '--icon', str(ROOT / 'packaging/windows/mathmaster.ico'),
         '--distpath', str(ROOT / 'artifacts'), '--workpath', str(ROOT / '.tools/build-updater'),
         '--specpath', str(ROOT / '.tools'), '--add-data', str(payload) + ';.', str(UPDATER)])
    outputs = [release] if args.package_only else [release, ROOT / 'artifacts' / (args.output_name+'.exe')]
    for output in outputs:
        output.with_suffix(output.suffix + '.sha256').write_text(
            updater.digest(output) + '  ' + output.name + '\n', encoding='ascii')
    (ROOT / 'artifacts' / (args.output_name+'-README.txt')).write_text('''master update / Windows x64

1. Copy master-update.exe to the Windows server (any folder).
2. Double-click it and select the EXISTING folder containing master.exe.
3. Click the update button. The latest release is embedded in this executable.
4. Wait for success, then refresh the browser with Ctrl+F5.

No Python or Node.js installation is required.
The updater stops this installation, verifies all new program files, backs up
the old runtime and SQLite databases, swaps the entire backend/frontend runtime,
restarts the server, and verifies health, frontend content and required APIs.
It keeps data/, config/, config.json, uploads, users and study records in place.
Keep all service windows under the same Windows login/session when updating.

Backups: <service folder>/.updates/<timestamp>/
Backups include private API configuration and databases. Keep them private.
If startup verification fails, the old runtime is restored automatically.
Database changes remain in place; a pre-update SQLite snapshot is retained for
manual recovery. Never restore a snapshot over a running service.
External integrations and optional hardware still need normal live acceptance.

Future versions: use the same updater and select the new master-release-*.zip,
or run a newer master-update.exe with its embedded release.
For developers: run scripts/build_server_update.py with native Windows Python.
It rebuilds frontend/backend and produces both state-free update formats.
Do not substitute the original private master.zip for a master-release ZIP.
'''.replace('master-update.exe',args.output_name+'.exe'), encoding='ascii')
    print(json.dumps({'version': version, 'files': len(files),
                      'outputs': [{'path': str(p), 'bytes': p.stat().st_size,
                                   'sha256': updater.digest(p)} for p in outputs]}))


if __name__ == '__main__':
    main()
