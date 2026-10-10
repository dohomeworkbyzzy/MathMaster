"""Build native Windows binaries and a per-user offline installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import urllib.request

from bootstrap import ROOT, source_hash


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True, env={**os.environ, 'PYTHONUTF8': '1'})


def include_runtime_sources(app):
    # PyPI's 0.19.5 release has no sdist; use the official, pinned source commit.
    url = 'https://codeload.github.com/moses-palmer/pystray/zip/c587fbe535610c177d49b585264762fa06abddca'
    with urllib.request.urlopen(url, timeout=40) as response:
        body = response.read(2_000_000)
    if hashlib.sha256(body).hexdigest() != '92735f0bf4b9f93bb41ab1e4cd75f3beac58aaf43ae51ab62f46fbdb83887061':
        raise RuntimeError('pystray source archive checksum mismatch')
    target = app/'THIRD_PARTY_SOURCES/pystray-0.19.5-source.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file():
        raise SystemExit('Python runtime LICENSE.txt not found; include it before distributing.')
    destination = app/'THIRD_PARTY_LICENSES/Python/LICENSE.txt'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', help='Inno Setup 7 ISCC.exe path')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('必须在 Windows 原生 Python 环境打包，不能用 WSL 的 Python 交叉编译。')
    if struct.calcsize('P') != 8:
        raise SystemExit('请使用 64 位 Python 构建 x64 安装版。')
    if not (ROOT/'dist/.source-hash').exists() or (ROOT/'dist/.source-hash').read_text() != source_hash():
        raise SystemExit('请先在 Windows 执行 npm ci 和 npm run build。')
    candidates = [args.iscc, shutil.which('ISCC.exe'), ROOT/'.tools/innosetup/ISCC.exe',
                  Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Inno Setup 7/ISCC.exe',
                  Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))/'Inno Setup 7/ISCC.exe']
    iscc = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if not iscc:
        raise SystemExit('请安装 Inno Setup 7，或通过 --iscc 指定 ISCC.exe。')
    run(sys.executable, ROOT/'scripts/package_release.py')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', ROOT/'artifacts/windows', '--workpath', ROOT/'artifacts/build-win',
        ROOT/'packaging/windows/MathMaster.spec')
    version = json.loads((ROOT/'package.json').read_text())['version']
    app = ROOT/'artifacts/windows/MathMaster'
    source = ROOT/'artifacts'/f'MathMaster-{version}-local.zip'
    # Keep the runtime's notices next to the program, and ship corresponding source.
    import zipfile
    with zipfile.ZipFile(source) as z:
        prefix = f'MathMaster-{version}/THIRD_PARTY_LICENSES/'
        for name in z.namelist():
            if name.startswith(prefix) and not name.endswith('/'):
                relative = Path(name[len(prefix):])
                output = app/'THIRD_PARTY_LICENSES'/relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(z.read(name))
    include_runtime_sources(app)
    run(iscc, f'/DAppVersion={version}', f'/DProjectRoot={ROOT}', ROOT/'packaging/windows/installer.iss')
    setup = ROOT/'artifacts'/f'MathMaster-Setup-{version}-x64.exe'
    setup.with_suffix('.exe.sha256').write_text(hashlib.sha256(setup.read_bytes()).hexdigest()+'  '+setup.name+'\n')
    print('Windows installer: '+str(setup))


if __name__ == '__main__':
    main()
