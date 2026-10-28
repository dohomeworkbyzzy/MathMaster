"""Second local OCR pass over source margins only, to read colored question numbers."""
import concurrent.futures,csv,io,json,os,subprocess,sys
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from prepare_local_pdf_library import SOURCE,SOURCES,ROOT,OUT

def work(task):
 key,pn=task;dest=OUT/'numbers'/key/f'{pn:03}.json'
 if dest.exists():return
 with fitz.open(SOURCE/SOURCES[key]) as d:
  p=d[pn-1];clip=fitz.Rect(20,50,125,p.rect.height-30);pix=p.get_pixmap(matrix=fitz.Matrix(4,4),clip=clip)
  # Sparse mode keeps independent question-number rows across large vertical gaps.
  r=subprocess.run([str(ROOT/'.tools/tesseract-wrapper'),'stdin','stdout','-l','eng','--psm','6','-c','tessedit_char_whitelist=0123456789.','tsv'],input=pix.tobytes('png'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,OMP_THREAD_LIMIT='1'),check=True)
  rows=[]
  for v in csv.DictReader(io.StringIO(r.stdout.decode()),delimiter='\t',quoting=csv.QUOTE_NONE):
   if v['text'].strip():rows.append({'text':v['text'],'bbox':[20+int(v['left'])/4,50+int(v['top'])/4,20+(int(v['left'])+int(v['width']))/4,50+(int(v['top'])+int(v['height']))/4]})
 dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(rows))
if __name__=='__main__':
 tasks=[(key,pn) for key,count in [('basea',150),('lla1',36),('lla2',37)] for pn in range(1,count+1)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for i,_ in enumerate(pool.map(work,tasks)):
   if i%30==0:print(i,flush=True)
