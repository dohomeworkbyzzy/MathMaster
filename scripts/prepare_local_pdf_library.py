"""Offline PDF layout/OCR cache for local study sources (never opens the live SQLite DB)."""
import argparse, concurrent.futures, csv, hashlib, io, json, os, re, subprocess, sys
from pathlib import Path
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('/mnt/d/study/t')
OUT=ROOT/'artifacts/new-pdfs'
CACHE=OUT/'ocr'
SOURCES={
 'yuq':'27张宇八套卷（数二试题册）.pdf',
 'yua':'27张宇八套卷（数二解析册）.pdf',
 'llq':'数二/做题本/【横版】27李林六套卷做题本.pdf',
 'lla1':'数二/27李林数二答案解析前3套.pdf',
 'lla2':'数二/27李林数二答案解析后三套.pdf',
 'baseq':'题本/【横版】李林基础500题.pdf',
 'basea':'PDF解析/解析册.pdf',
 'selq':'经验超市25往年模拟卷精选题/25往年模拟卷精选题 试题册.pdf',
 'sela':'经验超市25往年模拟卷精选题/25往年模拟卷精选题 解析册.pdf',
 'll880q':'27李林精讲精练880题-试题（数二）.pdf',
 'll880a':'【PDF】27版880参考答案.pdf'}

def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def page_cache(key,n):return CACHE/(key+'-'+digest_cached[key][:16])/f'{n+1:03}.json'
digest_cached={k:digest(SOURCE/v) for k,v in SOURCES.items()}

def extract(task, force_ocr=False):
 key,n=task;dest=page_cache(key,n)
 if dest.exists() and not force_ocr:return key,n,False
 with fitz.open(SOURCE/SOURCES[key]) as d:
  p=d[n];lines=[]
  for b in p.get_text('dict')['blocks']:
   for l in b.get('lines',[]):
    text=''.join(s['text'] for s in l['spans']).strip()
    if text:lines.append({'text':text,'bbox':list(l['bbox'])})
  mode='text'
  if force_ocr or len(p.get_text().strip())<30:
   mode='tesseract-chi_sim-eng';scale=2.4
   pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale));env=dict(os.environ,OMP_THREAD_LIMIT='1')
   result=subprocess.run([str(ROOT/'.tools/tesseract-wrapper'),'stdin','stdout','-l','chi_sim+eng','--psm','3','tsv'],input=pix.tobytes('png'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,check=True)
   grouped={}
   for row in csv.DictReader(io.StringIO(result.stdout.decode()),delimiter='\t',quoting=csv.QUOTE_NONE):
    if row.get('text','').strip():grouped.setdefault((row['block_num'],row['par_num'],row['line_num']),[]).append(row)
   for words in grouped.values():
    x=min(int(w['left']) for w in words);y=min(int(w['top']) for w in words)
    x1=max(int(w['left'])+int(w['width']) for w in words);y1=max(int(w['top'])+int(w['height']) for w in words)
    lines.append({'text':' '.join(w['text'] for w in words),'bbox':[x/scale,y/scale,x1/scale,y1/scale]})
  value={'source':SOURCES[key],'sha256':digest_cached[key],'page':n+1,'size':[p.rect.width,p.rect.height],'mode':mode,'lines':sorted(lines,key=lambda l:(round(l['bbox'][1]/3),l['bbox'][0]))}
 dest.parent.mkdir(parents=True,exist_ok=True);temp=dest.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(dest)
 return key,n,True

def load(key):
 with fitz.open(SOURCE/SOURCES[key]) as d:total=len(d)
 return [json.loads(page_cache(key,n).read_text(encoding='utf-8')) for n in range(total)]

def ocr():
 tasks=[]
 for k,v in SOURCES.items():
  with fitz.open(SOURCE/v) as d:tasks.extend((k,n) for n in range(len(d)))
 done=0
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for key,n,new in pool.map(extract,tasks):
   done+=1
   if done%20==0:print(f'OCR {done}/{len(tasks)} {key}:{n+1}',flush=True)
 print('OCR complete',len(tasks),flush=True)

if __name__=='__main__':ocr()
