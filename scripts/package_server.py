"""Snapshot the current installation into one private, portable master ZIP."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def bat(command):return ('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'+command+'\r\nif errorlevel 1 pause\r\nendlocal\r\n').encode('ascii')


def main():
    if os.name!='nt':raise SystemExit('Run with native Windows Python.')
    if '--repack' in sys.argv:
        finalize(ROOT/'artifacts/master');return
    from backend.ai.provider import config_path
    from backend.server_launcher import DEFAULT
    built=ROOT/'artifacts/server-build/master'
    if not (built/'master.exe').is_file():raise SystemExit('Build master.exe first.')
    destination=ROOT/'artifacts/master'
    if destination.exists():raise SystemExit('Destination already exists: '+str(destination))
    shutil.copytree(built,destination)
    data=destination/'data';data.mkdir()
    source=ROOT/'data'
    for name in ('mathmaster.db','ai-cache.db'):
        origin=source/name
        if origin.is_file():
            with closing(sqlite3.connect(str(origin),timeout=30)) as src,closing(sqlite3.connect(str(data/name))) as target:
                src.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
    for name in ('uploads','sources','models'):
        if (source/name).is_dir():shutil.copytree(source/name,data/name)
    # Network access is configured for the new server, not the old tunnel.
    (data/'network-access.json').write_text('{"allowed_origins":[]}\n',encoding='utf-8')
    config=destination/'config';config.mkdir()
    for name in ('provider.json','providers.json','capabilities.json'):
        origin=config_path().with_name(name)
        if origin.is_file():shutil.copyfile(origin,config/name)
    (destination/'config.json').write_text(json.dumps(DEFAULT,indent=2)+'\n',encoding='utf-8')
    (destination/'start.bat').write_bytes(bat('"%~dp0master.exe"'))
    (destination/'stop.bat').write_bytes(bat('"%~dp0master.exe" --stop'))
    (destination/'setup.bat').write_bytes(bat('"%~dp0master.exe" --configure'))
    (destination/'firewall.ps1').write_text('''$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
    exit
}
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Get-Content -Raw (Join-Path $root 'config.json') | ConvertFrom-Json
$port = [int]$config.port
$name = 'master-' + $port
if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port | Out-Null
}
Write-Host ('TCP ' + $port + ' allowed.')
Read-Host 'Press Enter to close'
''',encoding='utf-8')
    (destination/'firewall.bat').write_bytes(bat('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0firewall.ps1"'))
    (destination/'README.txt').write_text('''master / Windows x64

1. Extract the whole master folder to the server. Keep all files together.
2. Double-click start.bat. Keep the window open.
3. Open http://39.129.11.4:8509 (local: http://127.0.0.1:8509).
4. If needed, run firewall.bat to allow the configured TCP port.
   Also allow TCP 8509 in the server provider's security group/NAT settings.

stop.bat       Gracefully stop this folder's server.
setup.bat      Change the public URL and port, then restart.
config.json    Bind address, port, public origins, background indexing.
logs/          Server log (rotates automatically).
data/          Shared bank, users, personal records, original files, models.
config/        Migrated API settings, including private credentials.

No Python or Node.js installation is required. 64-bit Windows is required.
Default user: zzy. Two additional password-free registration slots.
Each user retains their own model choice and study records.
Remote API selection shows model names; provider websites and keys stay hidden.
API configuration management is available at the loopback URL on the server.
Use a reverse proxy and add its HTTPS origin in config.json if HTTPS is required.

This archive contains private API credentials and personal records. Keep it private.
For an update, stop the server first and preserve data/, config/ and config.json.
This is a foreground server; disconnecting RDP is different from logging off.
Optional OCR/DOCX page rendering still requires Tesseract/LibreOffice when used.
''',encoding='ascii')
    # Keep source and notices with the runtime, including the launcher itself.
    source_dir=destination/'source'
    for folder in ('backend','web','packaging'):
        shutil.copytree(ROOT/folder,source_dir/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('requirements.txt','requirements.lock','package.json','package-lock.json','vite.config.ts','tsconfig.json','index.html','LICENSE'):
        if (ROOT/name).is_file():shutil.copyfile(ROOT/name,source_dir/name)
    (source_dir/'scripts').mkdir(exist_ok=True)
    for name in ('bootstrap.py','stamp.mjs','package_server.py','check_server_package.py','verify_server_archive.py'):
        shutil.copyfile(ROOT/'scripts'/name,source_dir/'scripts'/name)
    license_dir=destination/'licenses';license_dir.mkdir()
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt',license_dir/'Python.txt')
    existing=ROOT/'artifacts/windows/MathMaster/THIRD_PARTY_LICENSES'
    if existing.is_dir():shutil.copytree(existing,license_dir/'third-party')
    import importlib.metadata
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            if '.dist-info' in str(entry) and any(word in entry.name.upper() for word in ('LICENSE','COPYING','NOTICE')):
                origin=Path(dist.locate_file(entry))
                if origin.is_file():
                    target=license_dir/'python'/str(entry);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
    finalize(destination)


def finalize(destination):
    # Every connection must close before hashing/zipping; Connection.__exit__
    # only commits and does not close SQLite or remove its journal sidecars.
    data=destination/'data'
    for name in ('mathmaster.db','ai-cache.db'):
        if (data/name).is_file():
            with closing(sqlite3.connect(str(data/name))) as c:c.execute('PRAGMA journal_mode=DELETE')
    with closing(sqlite3.connect(str(data/'mathmaster.db'))) as c:
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('papers','questions','users','attempts','history','ai_sessions','answer_submissions')}
    assert not list(data.glob('*.db-wal')) and not list(data.glob('*.db-shm'))
    for name in ('package_server.py','check_server_package.py','verify_server_archive.py'):
        shutil.copyfile(ROOT/'scripts'/name,destination/'source/scripts'/name)
    manifest={}
    for p in sorted(destination.rglob('*')):
        if p.is_file() and p!=destination/'manifest.json':
            with p.open('rb') as stream:manifest[p.relative_to(destination).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    output=ROOT/'artifacts/master.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for path in sorted(destination.rglob('*')):
            if path.is_file():z.write(path,Path('master')/path.relative_to(destination))
    with output.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  master.zip\n',encoding='ascii')
    print(json.dumps({'archive':str(output),'files':len(manifest),'bytes':output.stat().st_size,'record_counts':counts,'sha256':digest}))


if __name__=='__main__':main()
