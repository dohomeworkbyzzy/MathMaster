from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

root = Path(SPECPATH).parents[1]
hidden = ['backend.worker', 'backend.importer', 'backend.touchpad_native', 'backend.phonepad', 'pystray._win32', 'uvicorn.protocols.websockets.websockets_impl']
hidden += collect_submodules('sympy', filter=lambda name: not any(p in ('tests', 'benchmarks') for p in name.split('.')))
hidden += collect_submodules('uvicorn')
hidden += collect_submodules('backend.ai')
datas = [(str(root/'dist'), 'dist'), (str(root/'packaging/windows/mathmaster.ico'), 'packaging/windows')]
datas += collect_data_files('docx')
for package in ('sympy', 'pydantic', 'fastapi', 'pystray'):
    datas += copy_metadata(package)
a = Analysis([str(root/'packaging/windows/entry.py')], pathex=[str(root)],
             binaries=[], datas=datas, hiddenimports=hidden, hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=['pytest', 'IPython', 'matplotlib', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MathMaster',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, hide_console='hide-early', icon=str(root/'packaging/windows/mathmaster.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MathMaster')
