"""Build the standalone Windows maintenance tool, without an embedded release or private state."""
import hashlib,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 if os.name!='nt':raise SystemExit('Run with native Windows Python.')
 subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--name','master-maintenance',
  '--icon',str(ROOT/'packaging/windows/mathmaster.ico'),'--paths',str(ROOT/'packaging/windows'),
  '--distpath',str(ROOT/'artifacts'),'--workpath',str(ROOT/'.tools/build-maintenance'),
  '--specpath',str(ROOT/'.tools'),str(ROOT/'packaging/windows/server_updater.py')],cwd=ROOT,check=True)
 path=ROOT/'artifacts/master-maintenance.exe'
 with path.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
 path.with_suffix('.exe.sha256').write_text(h+'  '+path.name+'\n',encoding='ascii')
 print(path)
if __name__=='__main__':main()
