from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

root=Path(SPECPATH).parents[1]
hidden=['backend.worker','backend.ai.worker','backend.importer','backend.touchpad_native',
        'uvicorn.protocols.websockets.websockets_impl']
hidden+=collect_submodules('sympy',filter=lambda name:not any(p in ('tests','benchmarks') for p in name.split('.')))
hidden+=collect_submodules('uvicorn')+collect_submodules('backend.ai')
datas=[(str(root/'dist'),'dist')]+collect_data_files('docx')
for package in ('sympy','pydantic','fastapi','onnxruntime','tokenizers'):
    datas+=copy_metadata(package)
a=Analysis([str(root/'packaging/windows/server_entry.py')],pathex=[str(root)],binaries=[],datas=datas,
           hiddenimports=hidden,hookspath=[],hooksconfig={},runtime_hooks=[],
           excludes=['pytest','IPython','matplotlib','tkinter','pystray'])
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='master',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='master')
