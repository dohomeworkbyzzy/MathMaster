"""Read green book headings and parenthesized question numbers without formula noise."""
import concurrent.futures,csv,io,json,os,subprocess
from PIL import Image,ImageChops,ImageOps
import pymupdf as fitz
from prepare_local_pdf_library import ROOT,OUT,SOURCE,SOURCES,digest_cached

def work(task):
 key,pn=task;dest=OUT/'colored-structure'/(key+'-'+digest_cached[key][:16])/f'{pn:03}.json'
 if dest.exists():return
 with fitz.open(SOURCE/SOURCES[key]) as d:
  p=d[pn-1];pix=p.get_pixmap(matrix=fitz.Matrix(2.4,2.4));im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
  r,g,b=im.split();gr=ImageChops.subtract(g,r).point(lambda x:255 if x>13 else 0);gb=ImageChops.subtract(g,b).point(lambda x:255 if x>7 else 0)
  bw=ImageOps.invert(ImageChops.multiply(gr,gb));buf=io.BytesIO();bw.save(buf,'PNG')
  result=subprocess.run([str(ROOT/'.tools/tesseract-wrapper'),'stdin','stdout','-l','chi_sim+eng','--psm','11','tsv'],input=buf.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,OMP_THREAD_LIMIT='1'),check=True)
  grouped={}
  for row in csv.DictReader(io.StringIO(result.stdout.decode()),delimiter='\t',quoting=csv.QUOTE_NONE):
   if row.get('text','').strip():grouped.setdefault((row['block_num'],row['par_num'],row['line_num']),[]).append(row)
  rows=[]
  for ws in grouped.values():
   x=min(int(w['left']) for w in ws);y=min(int(w['top']) for w in ws);xx=max(int(w['left'])+int(w['width']) for w in ws);yy=max(int(w['top'])+int(w['height']) for w in ws)
   rows.append({'text':' '.join(w['text'] for w in ws),'bbox':[x/2.4,y/2.4,xx/2.4,yy/2.4]})
 dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(sorted(rows,key=lambda r:(round(r['bbox'][1]/3),r['bbox'][0])),ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':
 tasks=[(k,p) for k,count in [('ll880q',106),('ll880a',354)] for p in range(1,count+1)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for i,_ in enumerate(pool.map(work,tasks)):
   if i%30==0:print(i,flush=True)
