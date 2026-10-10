"""One-time setup, then offline startup. Windows and WSL use separate venvs."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def command(args):
    print('→ '+' '.join(str(a) for a in args),flush=True)
    if os.name=='nt' and str(args[0]).lower().endswith('.cmd'):
        subprocess.run(['cmd','/c',*map(str,args)],cwd=ROOT,check=True)
    else:subprocess.run(list(map(str,args)),cwd=ROOT,check=True)

def source_hash():
    paths=[*ROOT.joinpath('web').rglob('*'),*(ROOT/f for f in ('index.html','vite.config.ts','tsconfig.json','package.json','package-lock.json'))]
    paths=sorted((p for p in paths if p.is_file()),key=lambda p:p.relative_to(ROOT).as_posix())
    parts=''.join(p.relative_to(ROOT).as_posix()+'\n'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n' for p in paths)
    return hashlib.sha256(parts.encode()).hexdigest()

def open_browser(url):
    if os.environ.get('MATHMASTER_NO_BROWSER')=='1':return
    if os.name=='nt':
        candidates=[Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
                    Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft/Edge/Application/msedge.exe',
                    Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Google/Chrome/Application/chrome.exe',
                    Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe']
        for browser in candidates:
            if browser.is_file():
                subprocess.Popen([str(browser),'--app='+url,'--window-size=1000,740'],
                                 cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return
    webbrowser.open(url)

def main():
    if sys.version_info<(3,11):raise RuntimeError('请安装 Python 3.11 或更新版本（建议 3.13）。')
    env=ROOT/('.venv-win' if os.name=='nt' else '.venv')
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        print('首次启动：创建独立 Python 环境…',flush=True);venv.create(env,with_pip=True)
    signature=hashlib.sha256((ROOT/'requirements.lock').read_bytes()).hexdigest()
    stamp=env/'.mathmaster-deps'
    if not stamp.exists() or stamp.read_text()!=signature:
        command([python,'-m','pip','install','-r',ROOT/'requirements.lock'])
        stamp.write_text(signature)
    built=ROOT/'dist/.source-hash'
    if not built.exists() or built.read_text()!=source_hash():
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise RuntimeError('首次构建需要 Node.js 22.12+（建议 LTS）；安装后重新运行。')
        node=shutil.which('node')
        version=subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')
        if int(version[0])<22 or (int(version[0])==22 and int(version[1])<12):raise RuntimeError('请使用 Node.js 22.12 或更新版本。')
        command([npm,'ci']);command([npm,'run','build'])
    if '--setup-only' in sys.argv:
        print('本地运行环境与前端构建已准备完成。',flush=True);return
    url='http://127.0.0.1:8765'
    try:
        with urllib.request.urlopen(url+'/api/health',timeout=2) as response:
            if json.load(response).get('local'):
                print('MathMaster 已在运行，打开浏览器。');open_browser(url);return
    except Exception:pass
    print('\nMathMaster 启动中：'+url+'\n关闭启动窗口或 Ctrl+C 将停止本地服务。应用窗口可独立缩放或最小化。\n',flush=True)
    proc=subprocess.Popen([str(python),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765'],cwd=ROOT,env={**os.environ,'PYTHONUTF8':'1'})
    try:
        for _ in range(60):
            if proc.poll() is not None:raise RuntimeError('服务启动失败，请检查上方日志与端口占用。')
            try:
                with urllib.request.urlopen(url+'/api/health',timeout=1) as response:
                    if json.load(response).get('local'):open_browser(url);break
            except Exception:time.sleep(.5)
        proc.wait()
    except KeyboardInterrupt:pass
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('\n启动失败：'+str(e),file=sys.stderr);sys.exit(1)
