"""Create original-image question crops from cached 408 OCR/text positions."""
import argparse,collections,json,re,shutil
from functools import lru_cache
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from prepare_408_workbooks import OUT,ROOT
UPLOADS=ROOT/'data/uploads'
TOPICS={'os':'操作系统','ds':'数据结构','co':'计算机组成原理','cn':'计算机网络'}

def flat(s):return re.sub(r'\s+','',s)

def anchor(line,pg,scanned,key=None):
 t=flat(line['text']).replace('$','').replace('〖','').replace('了P','P');x,y,_,_=line['bbox'];w,h=pg['size']
 if not 0<=y/h<.925 or x/w>.22:return None
 if scanned:
  if re.match(r'^(?:[0-9SIlLO]{1,3}[.．、。,:：-]?[【\[\(（C£]+[Pp][0-9OIlSATSBGZ]|[0-9SIlLO]{1,3}[.．、。,:：-]?[【\[\(（]+[0-9]|[0-9SIlLO]{1,3}[.．]0P[0-9]|[【\[\(（]+P[0-9])',t):
   prefix=re.split('[Pp]',t,maxsplit=1)[0]
   prefix=prefix.translate(str.maketrans({'S':'5','s':'5','O':'0','I':'1','l':'1','L':'1'}))
   m=re.match(r'^[^\d]*([\d]{1,3})',prefix)
   return m[1] if m else '?'
 else:
  if key=='jc26-os' and not re.match(r'^\d+[.．、]',t):return None
  native=line['text'].strip()
  m=re.match(r'^(?:[（(](\d{1,3})[)）]|(\d{1,3})[.．、](?!\d))',native)
  if m:
   if re.match(r'[ABCD][.．、]',native[m.end():].strip()):return None
   return m[1] or m[2]
 return None

def build(source):
 key=source['key'];scanned=key.startswith('wd');topic=TOPICS[key.split('-')[1]]
 path=Path(source['path']);doc=fitz.open(path)
 @lru_cache(maxsize=4)
 def page_image(pn):
  page=doc[pn-1];scale=1800/(page.rect.width*.93)
  pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale))
  return Image.frombytes('RGB',[pix.width,pix.height],pix.samples),scale
 cached=[OUT/'ocr-v2'/key/f'{i+1:03}.json' for i in range(len(doc))]
 if not all(p.exists() for p in cached):return None
 pages=[json.loads(p.read_text(encoding='utf-8')) for p in cached]
 folder=f'workbook-408-{key}-{source["sha256"][:10]}-v3'
 dest=UPLOADS/folder;dest.mkdir(parents=True,exist_ok=True)
 if not (dest/'original.pdf').exists():shutil.copyfile(path,dest/'original.pdf')
 title=('2027 王道' if scanned else '2026 竟成速刷')+' · '+topic+' · 选择题做题本'
 paper={'id':folder,'title':title,'subject':'408','filename':folder+'/original.pdf','warnings':['用户提供做题本；参考答案由 AI 生成，待核对，不是原书答案。','原题截图为准，OCR 文字可能含误识别。']}
 anchors=[];section='';issues=[]
 for pg in pages:
  # Text-PDF front matter is a table of contents, not questions.
  if not scanned and sum('\uf001' in l['text'] for l in pg['lines'])>5:continue
  if key=='wd27-ds' and pg['page']==24:
   heading=next(l for l in pg['lines'] if flat(l['text']).startswith('4.2'))
   anchors.append({'page':24,'y':heading['bbox'][3]+8,'number':'1','section':heading['text'],'line':'source stem obscured'})
  if key=='jc26-co' and pg['page']==10:
   missing=next(l for l in pg['lines'] if l['text'].startswith('107 对应'))
   anchors.append({'page':10,'y':missing['bbox'][1]-3,'number':'2','section':'2.1 数制与编码','line':missing['text']})
  for line in pg['lines']:
   t=flat(line['text'])
   if re.match(r'^\d+\.\d+(?:\.\d+)?(?!\d)',t) and line['bbox'][0]/pg['size'][0]<.23 and not re.search(r'[Pp][0-9OIlSATSBGZ]',t) and anchor(line,pg,scanned,key) is None:
    section=line['text'][:200]
   n=anchor(line,pg,scanned,key)
   if n:
    y=max(0,line['bbox'][1]-(10 if scanned else 3))
    if anchors and pg['page']==anchors[-1]['page'] and abs(y-anchors[-1]['y'])<12:continue
    anchors.append({'page':pg['page'],'y':y,'number':n,'section':section,'line':line['text']})
 if not scanned:
  # The supplied text layer is authoritative for printed number markers. OCR fills gaps only;
  # Roman numerals in statements must not create additional questions.
  for pg in pages:
   extra=OUT/'ocr-native'/key/f'{pg["page"]:03}.json'
   if not extra.exists():raise ValueError('等待补充版面 OCR '+str(extra))
   ocr=json.loads(extra.read_text(encoding='utf-8'))
   for line in ocr['lines']:
    n=anchor(line,ocr,False,key)
    if not n:continue
    y=max(0,line['bbox'][1]-3)
    if any(a['page']==pg['page'] and abs(a['y']-y)<14 for a in anchors):continue
    t=flat(line['text'])
    if key!='jc26-os' and not re.match(r'^[（(]\d+[)）]',t):continue
    prior=sorted((a for a in anchors if (a['page'],a['y'])<(pg['page'],y)),key=lambda a:(a['page'],a['y']))
    previous=prior[-1] if prior else None
    number=int(n)
    heading=any(re.match(r'^\d+\.\d+',flat(l['text'])) and l['bbox'][1]<y and
        (previous is None or previous['page']<pg['page'] or previous['y']<l['bbox'][1]) for l in pg['lines'])
    if previous and number!=int(previous['number'])+1 and not(number==1 and heading):continue
    # A new stem needs an option group before the next already-known question.
    following=sorted((a for a in anchors if (a['page'],a['y'])>(pg['page'],y)),key=lambda a:(a['page'],a['y']))
    next_a=following[0] if following else {'page':len(doc),'y':pages[-1]['size'][1]*.925}
    if following and int(next_a['number'])==number:continue
    content=[]
    for pn in range(pg['page'],next_a['page']+1):
     op=OUT/'ocr-native'/key/f'{pn:03}.json';lo=y if pn==pg['page'] else 0;hi=next_a['y'] if pn==next_a['page'] else pages[pn-1]['size'][1]*.925
     content.extend(l['text'] for l in json.loads(op.read_text(encoding='utf-8'))['lines'] if lo<=l['bbox'][1]<hi)
    if not re.search(r'[ABCD][.．、]',flat(' '.join(content))):continue
    anchors.append({'page':pg['page'],'y':y,'number':n,'section':previous['section'] if previous else '', 'line':line['text']})
  anchors.sort(key=lambda a:(a['page'],a['y']))
 if not anchors:raise ValueError('没有找到题目 '+key)
 questions=[]
 for i,a in enumerate(anchors):
  b=anchors[i+1] if i+1<len(anchors) else None
  end=b['page'] if b else len(doc);images=[];texts=[];loc=[]
  for pn in range(a['page'],end+1):
   page=doc[pn-1];pg=pages[pn-1];w,h=pg['size']
   y0=a['y'] if pn==a['page'] else h*.025
   y1=b['y']-1 if b and pn==b['page'] else h*.925
   if y1-y0<h*.008:continue
   rect=fitz.Rect(w*.035,y0,w*.965,y1)
   name=f'{i+1:04}-{pn:03}.jpg';target=dest/name
   if not target.exists():
    img,scale=page_image(pn)
    img.crop(tuple(round(v*scale) for v in rect)).save(target,quality=91)
   images.append(folder+'/'+name)
   texts.extend(l['text'] for l in pg['lines'] if y0<=l['bbox'][1]<y1)
   loc.append({'page':pn,'clip':list(rect)})
  raw='\n'.join(texts)
  # Source numbering repeats by section. Store an unambiguous sequence and keep source location in text/spec.
  number=str(i+1);qid=folder+f'-q{i+1:04}'
  info=f'{title}\n{a["section"]}\n原书题号 {a["number"]} · PDF 第 {a["page"]} 页\n'
  multi_blank=not scanned and len(re.findall(r'(?:^|\n)(?:[（(]\d+[)）])?\s*A[.．]',raw))>1
  spec={'kind':'subjective' if multi_blank else 'mcq','max_points':1,'points_known':False,'answer_key':'','solution':'','verified':False,'source':'用户提供：'+path.name,'answer_origin':'missing','reference_issue':'尚无参考答案，待生成与核对。','source_sha256':source['sha256'],'source_locations':loc,'source_number':a['number'],'section':a['section']}
  q={'id':qid,'paper_id':folder,'number':number,'text':info+raw,'images':images,'reference_answer':'','subject':'408','confirmed':False,'spec':spec}
  if not images:raise ValueError('无截图 '+qid)
  if a['number']=='?':issues.append({'id':qid,'issue':'source_number_ocr_uncertain','page':a['page']})
  questions.append(q)
 plan={'papers':[paper],'questions':questions,'issues':issues,'source':source}
 plans=OUT/'plans';plans.mkdir(exist_ok=True)
 (plans/(key+'.json')).write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
 print(key,len(questions),'questions',len(issues),'number warnings',flush=True)
 return plan

def main():
 p=argparse.ArgumentParser();p.add_argument('--key');a=p.parse_args()
 sources=json.loads((OUT/'sources.json').read_text(encoding='utf-8'));allplans=[]
 for s in sources:
  if a.key and a.key!=s['key']:continue
  result=build(s)
  if result:allplans.append(result)
 if allplans:
  merged={name:[v for plan in allplans for v in plan[name]] for name in ('papers','questions','issues')}
  (OUT/'import-plan.json').write_text(json.dumps(merged,ensure_ascii=False),encoding='utf-8')
  print('TOTAL',len(merged['papers']),len(merged['questions']),flush=True)
if __name__=='__main__':main()
