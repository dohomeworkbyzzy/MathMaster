"""Package tracked source + locally built frontend; never include user data."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import zipfile

from bootstrap import ROOT, source_hash


def main():
    stamp = ROOT / 'dist/.source-hash'
    if not stamp.is_file() or stamp.read_text() != source_hash():
        raise SystemExit('请先执行 npm ci 和 npm run build，确保前端与源码一致。')
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).decode().split('\0')
    files = {}
    for name in filter(None, names):
        path = ROOT / name
        if path.is_file():
            if path.parts[len(ROOT.parts)] in ('data', '.venv', '.venv-win', 'node_modules', '.tools', 'artifacts'):
                raise SystemExit('拒绝打包个人数据或本机环境：' + name)
            files[name] = path.read_bytes()
    for path in (ROOT / 'dist').rglob('*'):
        if path.is_file():
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    # Preserve notices shipped with installed distributions, including fonts.
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            if '.dist-info' in str(entry) and any(word in entry.name.upper() for word in ('LICENSE', 'COPYING', 'NOTICE')):
                path = Path(dist.locate_file(entry))
                if path.is_file():
                    files['THIRD_PARTY_LICENSES/python/' + str(entry)] = path.read_bytes()
    node_modules = ROOT / 'node_modules'
    for path in node_modules.rglob('*'):
        if path.is_file() and any(path.name.upper().startswith(word) for word in ('LICENSE', 'COPYING', 'NOTICE')):
            files['THIRD_PARTY_LICENSES/npm/' + path.relative_to(node_modules).as_posix()] = path.read_bytes()
    version = json.loads((ROOT / 'package.json').read_text())['version']
    folder = 'MathMaster-' + version
    output = ROOT / 'artifacts' / (folder + '-local.zip')
    output.parent.mkdir(exist_ok=True)
    manifest = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}
    files['MANIFEST.sha256.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            archive.writestr(folder + '/' + name, body)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(checksum + '  ' + output.name + '\n')
    print(f'{output}\n{len(files)} files; SHA256 {checksum}')


if __name__ == '__main__':
    main()
