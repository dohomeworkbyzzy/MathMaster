"""Read math-II 880 book structure and join solutions by chapter/level/type/number."""
import collections,json,re
from pathlib import Path
import build_local_pdf_plan as b
from prepare_local_pdf_library import digest_cached
QSTART=[9,11,16,17,23,30,31,37,45,47,49,53,54,57,60,61,63,67,68,70,72,73,75,78,79,80,83,84,87,90,91,94,98,99,101,106,107]
ASTART=[3,9,25,29,49,70,73,95,129,134,144,158,160,172,188,193,201,219,221,225,231,233,242,249,250,255,262,264,271,282,284,296,315,317,326,347,355]
LEVELS=['基础题','综合题','拓展题'];KINDS=['mcq','fill','subjective']
MANUAL={'ll880q':{30:351,72:78,73:154,80:588,90:393,94:316},'ll880a':{25:498,188:315,233:136}}

def green(key,pn):return json.loads((b.OUT/'colored-structure'/(key+'-'+digest_cached[key][:16])/f'{pn:03}.json').read_text(encoding='utf-8'))
def header(key,pn,level):
 if pn>len(b.pages(key)):return {'page':pn,'y':0}
 choices=[l for l in green(key,pn)+b.pages(key)[pn-1]['lines'] if level[:2] in b.flat(l['text']) and l['bbox'][0]>150]
 if choices:return {'page':pn,'y':min(l['bbox'][1] for l in choices)-8}
 if pn in MANUAL[key]:return {'page':pn,'y':MANUAL[key][pn]-8}
 # Only the centered colored level heading is eligible, not chapter/page headers or formulas.
 choices=[l for l in green(key,pn) if 180<l['bbox'][0]<285 and 25<l['bbox'][2]-l['bbox'][0]<100 and 65<l['bbox'][1]<700 and l['bbox'][3]-l['bbox'][1]>12]
 if len(choices)==1:return {'page':pn,'y':choices[0]['bbox'][1]-8}
 raise ValueError(f'请核对层级标题 {key} {pn} {level}: {choices}')

def numeric(t):
 s=b.flat(t)
 for c in ['（','{','《','〈','【','〔']:s=s.replace(c,'(')
 for c in ['）','}','》','〉','】','〕']:s=s.replace(c,')')
 m=re.match(r'^[(\[]?(\d{1,3})[)\]]',s)
 return int(m[1]) if m else None

def section_events(key,start,end):
 events=[]
 for pn in range(start['page'],min(end['page'],len(b.pages(key)))+1):
  gl=green(key,pn);plain=b.pages(key)[pn-1]['lines'];candidates=[]
  def inside(y):return (pn,y)>=(start['page'],start['y']) and (pn,y)<(end['page'],end['y']) and y>40
  for l in gl:
   x,y,xx,yy=l['bbox'];s=b.flat(l['text'])
   if not inside(y) or not 20<x<95 or xx-x>42:continue
   n=numeric(s)
   if n is None and not (9<xx-x<38 and (re.search(r'[（()）{}《〈【\[]',s) or (re.fullmatch(r'[A-Za-z0-9.,]+',s) and (xx-x)/max(1,yy-y)>1.7))):continue
   if re.search('解答|选择|填空',s):continue
   near=[v for v in plain if abs(v['bbox'][1]-y)<13 and abs(v['bbox'][0]-x)<8 and numeric(v['text']) is not None]
   ns=list(dict.fromkeys([numeric(v['text']) for v in near]+([n] if n else [])))
   candidates.append({'page':pn,'y':max(62,min([y]+[v['bbox'][1] for v in near])-12),'ns':ns,'green':s,'plain':[v['text'][:70] for v in near],'marker_ratio':(xx-x)/max(1,yy-y),'marker_box':[x,y,xx,yy]})
  # Full OCR recovers a colored question marker that sparse OCR omitted.
  for l in plain:
   x,y,xx,yy=l['bbox'];n=numeric(l['text'])
   if n is None or not inside(y) or not 20<x<95:continue
   if any(abs(c['y']+12-y)<14 for c in candidates):continue
   if any(abs(g['bbox'][1]-y)<14 and abs(g['bbox'][0]-x)<8 and g['bbox'][2]-g['bbox'][0]<40 for g in gl):
    candidates.append({'page':pn,'y':max(62,y-12),'ns':[n],'green':'recovered','plain':[l['text'][:70]],'marker_box':[x,y,x+22,y+12]})
  for l in plain+gl:
   x,y,xx,yy=l['bbox'];t=b.flat(l['text'])
   if not inside(y) or x>110 or len(t)>20:continue
   for stage,word in enumerate(['选择','填空','解答']):
    if word in t:events.append({'page':pn,'y':y-5,'stage_header':stage})
  merged=[]
  for event in sorted(candidates,key=lambda e:e['y']):
   if merged and abs(merged[-1]['y']-event['y'])<13:
    merged[-1]['ns']=list(dict.fromkeys(merged[-1]['ns']+event['ns']));continue
   merged.append(event)
  events+=merged
 return sorted(events,key=lambda e:(e['page'],e['y']))

def structure(key,starts,targets=None):
 bounds=[header(key,pn,LEVELS[i%3]) for i,pn in enumerate(starts[:-1])]+[{'page':starts[-1],'y':0}]
 out={};warnings=[]
 for i,start in enumerate(bounds[:-1]):
  stage=2 if i%3==2 else 0;expected=1;events=section_events(key,start,bounds[i+1]);floors={stage:start};pool=collections.defaultdict(list)
  headers=[e for e in events if 'stage_header' in e]
  for event in events:
   if 'stage_header' in event:
    target=event['stage_header']
    if target>stage:stage=target;expected=1;floors[stage]=event
    continue
   if any(h['page']==event['page'] and abs(h['y']+5-event['y']-12)<10 for h in headers):continue
   x,y,_,_=event['marker_box']
   number_file=b.OUT/'880-number-crops'/(key+'-'+digest_cached[key][:16])/f"{event['page']:03}-{int(x*10):04}-{int(y*10):05}.json"
   try:focused=json.loads(number_file.read_text()) if number_file.exists() else {}
   except json.JSONDecodeError:focused={}
   ns=[expected] if expected in event['ns'] else ([focused['number']] if focused.get('number') else [n for n in event['ns'] if 1<=n<=90])
   event={**event,'ns':ns,'focused':focused.get('raw','')}
   pool[stage].append(event)
   if not ns:continue
   if expected in ns:n=expected
   elif 1 in ns and expected>1 and stage<2 and (event.get('marker_ratio',1)<1.7 or focused.get('number')==1) and not any(h['stage_header']==stage+1 and (h['page'],h['y'])>(event['page'],event['y']) for h in headers):
    stage+=1;expected=1;n=1;floors[stage]=event;pool[stage].append(event)
   else:
    viable=[n for n in ns if expected<=n<=expected+5]
    if not viable:continue
    n=min(viable)
   identity=(i,stage,n)
   if identity in out:continue
   out[identity]={**event,'number':n};expected=n+1
  for st in range(3):
   known=sorted(n for ii,ss,n in out if ii==i and ss==st)
   if not known:continue
   maximum=max(max(known),(targets or {}).get((i,st),0))
   missing=[n for n in range(1,maximum+1) if (i,st,n) not in out]
   runs=[]
   for n in missing:
    if runs and n==runs[-1][-1]+1:runs[-1].append(n)
    else:runs.append([n])
   for run in runs:
    prev=out.get((i,st,run[0]-1),floors.get(st,start));nxt=next((out[(i,st,j)] for j in range(run[-1]+1,maximum+1) if (i,st,j) in out),None)
    if nxt is None:nxt=next((v for (ii,ss,nn),v in sorted(out.items()) if ii==i and ss>st),bounds[i+1])
    used={(v['page'],v['y']) for (ii,ss,_),v in out.items() if ii==i}
    options=[e for e in pool[st] if (prev['page'],prev['y'])<(e['page'],e['y'])<(nxt['page'],nxt['y']) and (e['page'],e['y']) not in used]
    if not options:
     for pn in range(prev['page'],min(nxt['page'],len(b.pages(key)))+1):
      for l in b.pages(key)[pn-1]['lines']:
       x,y,xx,yy=l['bbox'];num=numeric(l['text'])
       if num not in run or not 25<x<120:continue
       yy0=max(40,y-12)
       if (prev['page'],prev['y'])<(pn,yy0)<(nxt['page'],nxt['y']):options.append({'page':pn,'y':yy0,'ns':[num],'green':'full OCR gap recovery','plain':[l['text'][:100]],'marker_box':[x,y,x+22,y+12]})
    if len(options)==len(run):
     for n,event in zip(run,sorted(options,key=lambda e:(e['page'],e['y']))):
      out[i,st,n]={**event,'number':n};warnings.append({'section':i,'stage':st,'expected':n,'event':event,'issue':'isolated_number_reading_repaired'})
    else:warnings.append({'section':i,'stage':st,'expected':run,'issue':'unresolved_number_gap','options':options})
 corrections={'ll880q':{(9,1,2):(48,282),(9,1,3):(48,321),(11,0,1):(53,145),(11,2,1):(53,310),(26,2,1):(83,110)},'ll880a':{(3,2,14):(45,151),(3,2,15):(45,207),(7,2,1):(109,130),(13,2,11):(181,509),(11,0,1):(158,309),(11,2,1):(159,111),(26,2,1):(262,610)}}
 for identity,(pn,y) in corrections[key].items():
  out[identity]={'page':pn,'y':y,'number':identity[2],'ns':[identity[2]],'green':'visually checked source number','plain':[]}
 warnings=[w for w in warnings if w['issue']!='unresolved_number_gap' or any((w['section'],w['stage'],n) not in out for n in w['expected'])]
 return dict(sorted(out.items())),bounds,warnings

def fit_question_boundaries(markers):
 """Snap dense question clips to whitespace while retaining complete number glyphs.
 Full OCR line boxes can include a neighboring superscript; source pixels decide the clip.
 """
 from PIL import Image,ImageChops
 current_page=None;previous=None;scale=2
 for identity,event in sorted(markers.items()):
  pn=event['page']
  if pn!=current_page:
   page=b.doc('ll880q')[pn-1];pix=page.get_pixmap(matrix=b.fitz.Matrix(scale,scale));im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
   red,grn,blue=im.split();gm=ImageChops.multiply(ImageChops.subtract(grn,red).point(lambda v:255 if v>13 else 0),ImageChops.subtract(grn,blue).point(lambda v:255 if v>7 else 0))
   dark=im.convert('L').point(lambda v:255 if v<175 else 0).crop((35*scale,0,im.width-20*scale,im.height));rows=dark.getprojection()[1];current_page=pn
  if 'marker_box' not in event:
   previous=None;continue
  x,y,xx,yy=event['marker_box'];floor=previous['end']+1 if previous and previous['page']==pn else 45
  lo=max(floor,y-8);hi=min(page.rect.height-20,y+28)
  area=gm.crop((int(max(0,x-1)*scale),int(lo*scale),int(min(page.rect.width,x+21)*scale),int(hi*scale)))
  projection=area.getprojection()[1];runs=[];start=None
  for j,v in enumerate(projection+[0]):
   if v and start is None:start=j
   if not v and start is not None:
    if j-start>=6:runs.append((lo+start/scale,lo+j/scale))
    start=None
  glyph=runs[0] if runs else (y,yy)
  previous_floor=floor
  top=min(glyph[0],event['y']+12) if event['y']+12>previous_floor+1 else glyph[0]
  low=max(previous_floor,glyph[0]-35);high=top
  blanks=[];start=None
  for j in range(max(0,int(low*scale)),min(len(rows),int(high*scale))+1):
   if not rows[j] and start is None:start=j
   if rows[j] and start is not None:
    if j-start>=3:blanks.append((start,j))
    start=None
  if start is not None and int(high*scale)-start>=3:blanks.append((start,int(high*scale)))
  original=event['y']
  if blanks:event['y']=(blanks[-1][0]+blanks[-1][1])/(2*scale)
  else:event['y']=max(previous_floor,min(original,glyph[0]-1))
  event['pixel_prefix']=[glyph[0],glyph[1]];event['original_ocr_clip_y']=original
  previous={'page':pn,'end':glyph[1]}
 return markers

def main():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--build',action='store_true');args=parser.parse_args()
 q,qb,qw=structure('ll880q',QSTART);a,ab,aw=structure('ll880a',ASTART)
 targets=collections.defaultdict(int)
 for i,st,n in q:targets[i,st]=max(targets[i,st],n)
 q,qb,qw=structure('ll880q',QSTART,targets);a,ab,aw=structure('ll880a',ASTART,targets)
 q=fit_question_boundaries(q)
 counts=lambda data:collections.Counter((i,s) for i,s,n in data)
 qc,ac=counts(q),counts(a);mismatches=[{'section':i,'chapter':i//3+1,'level':LEVELS[i%3],'kind':KINDS[s],'questions':qc[i,s],'solutions':ac[i,s]} for i,s in sorted(set(qc)|set(ac)) if qc[i,s]!=ac[i,s]]
 report={'questions':len(q),'solutions':len(a),'mismatches':mismatches,'question_warnings':qw,'solution_warnings':aw,'question_markers':{str(k):v for k,v in q.items()},'solution_markers':{str(k):v for k,v in a.items()}}
 (b.OUT/'880-structure-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if 'markers' not in k},ensure_ascii=False,indent=2),flush=True)
 if not args.build:return
 if mismatches:raise ValueError('题目/解析数目不一致，先核对')
 for ci,chapter in enumerate(b.CHAPTERS):
  pid=f'local-lilin-880-math2-ch{ci+1:02}';b.addpaper(pid,f'2027 李林880题 · 数学二 · 第{ci+1}章 {chapter}','ll880q')
  for level in range(3):
   i=ci*3+level
   for stage in range(3):
    count=qc[i,stage]
    for n in range(1,count+1):
     identity=(i,stage,n);qn=q[identity];an=a[identity]
     qnext=next((v for k,v in q.items() if k>identity),None);anext=next((v for k,v in a.items() if k>identity),None)
     if qb[i+1]['page']<=len(b.pages('ll880q')) and (qnext is None or (qb[i+1]['page'],qb[i+1]['y'])<(qnext['page'],qnext['y'])):qnext=qb[i+1]
     if ab[i+1]['page']<=len(b.pages('ll880a')) and (anext is None or (ab[i+1]['page'],ab[i+1]['y'])<(anext['page'],anext['y'])):anext=ab[i+1]
     qi,qt,ql=b.segment('ll880q',qn,qnext,len(b.pages('ll880q')),True);ai,at,al=b.segment('ll880a',an,anext,len(b.pages('ll880a')))
     b.addq(pid,n,'ll880q',qi,qt,ql,'',ai,at,al,chapter=chapter+' · '+LEVELS[level],kind=KINDS[stage],reference_key='ll880a',qid=pid+f'-{level+1}-{stage+1}-q{n:03}')
 manifest={'version':1,'sources':[{'key':k,'filename':b.SOURCES[k],'sha256':digest_cached[k],'pages':len(b.pages(k))} for k in ['ll880q','ll880a']],'papers':b.PAPERS,'questions':b.QUESTIONS,'excluded':[],'issues':[],'classification':'数学二；章节/基础综合拓展/题型分组；本地 OCR 草稿待核对'}
 (b.OUT/'880-import-plan.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print('plan built',len(b.QUESTIONS),flush=True)
if __name__=='__main__':main()
