"""Cache text/OCR positions from the eight supplied 408 workbooks; keep originals intact."""
import concurrent.futures,csv,hashlib,io,json,os,subprocess
from pathlib import Path
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/408-workbooks'
SOURCE=Path('/mnt/d/study/t')

def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def sources():
 result=[]
 for p in sorted(SOURCE.rglob('*.pdf')):
  if '王道' not in p.name and '竟成' not in p.name:continue
  topic=next(t for t,words in [('os',['操作系统']),('ds',['数据结构']),('co',['计组','组成原理']),('cn',['计网','计算机网络'])] if any(w in p.name for w in words))
  result.append({'key':('wd27-' if '王道' in p.name else 'jc26-')+topic,'path':str(p),'sha256':sha(p)})
 return result

def extract(task):
 s,n=task;dest=OUT/'ocr-native'/s['key']/f'{n+1:03}.json'
 if dest.exists():return
 with fitz.open(s['path']) as d:
  p=d[n];lines=[];mode='text'
  for b in p.get_text('dict')['blocks']:
   for l in b.get('lines',[]):
    t=''.join(x['text'] for x in l['spans']).strip()
    if t:lines.append({'text':t,'bbox':list(l['bbox'])})
  if True:
   mode='ocr';scale=2000/p.rect.width
   pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale))
   r=subprocess.run([str(ROOT/'.tools/tesseract-wrapper'),'stdin','stdout','-l','chi_sim+eng','--psm','6','tsv'],input=pix.tobytes('png'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
   groups={}
   for row in csv.DictReader(io.StringIO(r.stdout.decode()),delimiter='\t',quoting=csv.QUOTE_NONE):
    if row.get('text','').strip():groups.setdefault((row['block_num'],row['par_num'],row['line_num']),[]).append(row)
   for words in groups.values():
    x=min(int(w['left']) for w in words);y=min(int(w['top']) for w in words)
    x1=max(int(w['left'])+int(w['width']) for w in words);y1=max(int(w['top'])+int(w['height']) for w in words)
    lines.append({'text':' '.join(w['text'] for w in words),'bbox':[x/scale,y/scale,x1/scale,y1/scale]})
  dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_text(json.dumps({'page':n+1,'size':[p.rect.width,p.rect.height],'mode':mode,'lines':sorted(lines,key=lambda l:(l['bbox'][1],l['bbox'][0]))},ensure_ascii=False),encoding='utf-8')

def main():
 OUT.mkdir(parents=True,exist_ok=True);src=[s for s in sources() if s['key'].startswith('jc')];(OUT/'native-sources.json').write_text(json.dumps(src,ensure_ascii=False,indent=2),encoding='utf-8')
 tasks=[]
 for s in src:
  with fitz.open(s['path']) as d:tasks.extend((s,n) for n in range(len(d)))
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
  for i,_ in enumerate(pool.map(extract,tasks),1):
   if i%20==0:print('Layout/OCR',i,'/',len(tasks),flush=True)
 print('complete',len(tasks),flush=True)
if __name__=='__main__':main()
