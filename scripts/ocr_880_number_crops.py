"""Focused local number OCR, independent of formulas, options and solution body text."""
import concurrent.futures,json,os,re,subprocess,threading
from pathlib import Path
import pymupdf as fitz
from PIL import Image,ImageOps
import io
import build_880_pdf_plan as b
from prepare_local_pdf_library import ROOT,SOURCE,SOURCES,OUT,digest_cached
local=threading.local()
def dest(key,event):
 x,y,xx,yy=event['marker_box'];return OUT/'880-number-crops'/(key+'-'+digest_cached[key][:16])/f"{event['page']:03}-{int(x*10):04}-{int(y*10):05}.json"
def work(task):
 key,e=task;path=dest(key,e)
 if path.exists():return
 if not hasattr(local,'docs'):local.docs={}
 if key not in local.docs:local.docs[key]=fitz.open(SOURCE/SOURCES[key])
 p=local.docs[key][e['page']-1];x,y,xx,yy=e['marker_box'];clip=fitz.Rect(max(0,x-2),max(0,y-3),min(p.rect.width,x+23),min(p.rect.height,y+14))
 pix=p.get_pixmap(matrix=fitz.Matrix(6,6),clip=clip);im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples).convert('L');im=ImageOps.expand(im,border=15,fill='white');buf=io.BytesIO();im.save(buf,'PNG')
 result=subprocess.run([str(ROOT/'.tools/tesseract-wrapper'),'stdin','stdout','-l','eng','--psm','7','-c','tessedit_char_whitelist=0123456789()'],input=buf.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,OMP_THREAD_LIMIT='1'),check=True)
 raw=result.stdout.decode().strip();m=re.match(r'^\(?([1-9][0-9]{0,2})\)',raw)
 value={'raw':raw,'number':int(m[1]) if m else None,'page':e['page'],'clip':list(clip)}
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)
if __name__=='__main__':
 tasks=[]
 for key,starts in [('ll880q',b.QSTART),('ll880a',b.ASTART)]:
  bounds=[b.header(key,pn,b.LEVELS[i%3]) for i,pn in enumerate(starts[:-1])]+[{'page':starts[-1],'y':0}]
  for i,start in enumerate(bounds[:-1]):
   tasks.extend((key,e) for e in b.section_events(key,start,bounds[i+1]) if 'marker_box' in e)
 print('tasks',len(tasks),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for i,_ in enumerate(pool.map(work,tasks)):
   if i%100==0:print(i,flush=True)
