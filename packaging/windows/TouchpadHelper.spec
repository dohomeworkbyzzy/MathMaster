from pathlib import Path
root = Path(SPECPATH).parents[1]
a = Analysis([str(root/'packaging/windows/touchpad_entry.py')], pathex=[str(root)],
             binaries=[], datas=[], hiddenimports=['backend.touchpad_helper', 'backend.touchpad_native'],
             excludes=['pytest', 'sympy', 'numpy', 'PIL', 'fastapi', 'uvicorn', 'torch', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MathMasterTouchpad',
          console=True, debug=False, strip=False, upx=False)
