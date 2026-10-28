"""Create reviewable, idempotent question/solution crops and a math-II-only import manifest.
Uses local OCR/layout cache; never calls an LLM and never writes learner data.
"""
import collections, json, re, shutil, sys
from pathlib import Path
import pymupdf as fitz
from PIL import Image,ImageChops
from prepare_local_pdf_library import ROOT,SOURCE,SOURCES,OUT,load,digest_cached
UPLOADS=ROOT/'data/uploads/local-pdf-20261014'
UPLOADS.mkdir(parents=True,exist_ok=True)
PAGES={};DOCS={};ISSUES=[]
def pages(key):
 if key not in PAGES:PAGES[key]=load(key)
 return PAGES[key]
def doc(key):
 if key not in DOCS:DOCS[key]=fitz.open(SOURCE/SOURCES[key])
 return DOCS[key]
def flat(s):return re.sub(r'\s+','',s)
def text(key,page):return '\n'.join(l['text'] for l in pages(key)[page-1]['lines'])
def number(s):
 s=flat(s).replace('．','.').replace('。','.').replace('、','.').replace(',','.').replace('，','.')
 s=re.sub(r'^[lI丨][.]','1.',s)
 m=re.match(r'^(\d{1,3})(?:\.|(?=[【（(]|答案|解析|证明|解[:：]))',s)
 return int(m[1]) if m else None

def anchors(key,start,end,count,answer=False):
 candidates=collections.defaultdict(list)
 for pg in pages(key)[start-1:end]:
  start_cut=0;end_cut=pg['size'][1]
  if key=='basea' and pg['page']==start:
   heads=[l['bbox'][1] for l in pg['lines'] if re.search('概念.*篇|计算.*方法',flat(l['text']))]
   if heads:start_cut=min(heads)
  if key=='basea' and pg['page']==end and end<150:
   heads=[l['bbox'][1] for l in pg['lines'] if re.search('概念.*篇|计算.*方法',flat(l['text']))]
   if heads:end_cut=min(heads)
  labels_path=OUT/'labels'/key/f"{pg['page']:03}.json"
  labels=json.loads(labels_path.read_text()) if labels_path.exists() else []
  def near_label(x,y):return any(abs(y-box[1])<9 and x<=box[0]+5 for box in labels)
  for l in pg['lines']:
   x,y,x1,y1=l['bbox'];n=number(l['text'])
   if key=='basea' and not near_label(x,y):continue
   if key in ('selq','sela') and (not re.search(r'卷|套|张|李|余|超|】|[（(【\[]|[)）]$',l['text']) or re.search('答案|解析',l['text'])):continue
   if y<start_cut or y>=end_cut:continue
   if not n or not 1<=n<=count or x>170 or y<7 or y>pg['size'][1]-30:continue
   if answer and key=='yua' and not re.search(r'【|答案|【解|【证|Y证',flat(l['text'])):continue
   candidates[n].append({'page':pg['page'],'y':max(12,y-9),'line':l['text']})
  numbers_path=OUT/'numbers'/key/f"{pg['page']:03}.json"
  for l in json.loads(numbers_path.read_text()) if numbers_path.exists() else []:
   x,y,_,_=l['bbox']
   if y<start_cut or y>=end_cut or not near_label(x,y):continue
   m=re.match(r'^(\d+)',l['text'])
   if not m:continue
   ns=[int(m[1])]
   if '.' not in l['text'] and len(m[1])>1:ns+=[int(m[1][:-1])]
   for n in ns:
    if 1<=n<=count:candidates[n].append({'page':pg['page'],'y':max(12,y-9),'line':'margin OCR '+l['text']})

 # Pinned corrections are visually checked source positions, not inferred formula values.
 corrections={'yuq':{(29,11):610,(29,13):725,(46,13):55},'lla1':{(5,11):768,(19,16):328,(26,5):266},'lla2':{(1,1):726,(8,16):309,(28,8):391,(26,5):648,(30,12):575},'basea':{(24,26):577,(80,15):272,(91,11):475,(97,4):79,(109,9):482,(121,4):334,(123,11):111,(127,15):340},'selq':{(27,67):74,(61,11):92,(19,44):55},'sela':{(12,24):115,(39,83):777,(42,87):308},'yua':{(38,19):209}}
 for (pn,n),y in corrections.get(key,{}).items():
  if start<=pn<=end:
   headings=[l['bbox'][1] for l in pages(key)[pn-1]['lines'] if re.search('概念.*篇|计算.*方法',flat(l['text']))] if key=='basea' else []
   if headings and ((pn==start and y<min(headings)) or (pn==end and end<150 and y>=min(headings))):continue
   candidates[n]=[{'page':pn,'y':y,'line':'visually checked question number'}]
 out={};previous=(start,0)
 for n in range(1,count+1):
  options=sorted((v for v in candidates[n] if (v['page'],v['y'])>previous),key=lambda v:(v['page'],v['y']))
  if options:out[n]=options[0];previous=(options[0]['page'],options[0]['y'])
 for n in range(1,count+1):
  if n not in out:ISSUES.append({'source':key,'section_pages':[start,end],'number':n,'issue':'question_anchor_missing' if not answer else 'solution_anchor_missing'})
 return out

def segment(key,anchor,next_anchor,end,stem=False):
 if anchor is None:return [],'',[]
 start=anchor['page'];last=next_anchor['page'] if next_anchor else end
 assets=[];texts=[];locations=[]
 for pn in range(start,last+1):
  page=doc(key)[pn-1];height=page.rect.height
  y0=anchor['y'] if pn==start else 45
  y1=next_anchor['y']-1 if next_anchor and pn==last else height-(18 if key.startswith('ll880') else 45)
  if y1-y0<12:continue
  # Full-width clips retain roots, superscripts, diagrams, and multi-column options.
  rect=fitz.Rect(24,max(6,y0),page.rect.width-20,min(height-20,y1))
  name=f'{key}-p{pn:03}-y{int(y0):04}-{int(y1):04}.png';path=UPLOADS/name
  if not path.exists():page.get_pixmap(matrix=fitz.Matrix(2.4,2.4),clip=rect).save(path)
  assets.append('local-pdf-20261014/'+name)
  texts.extend(l['text'] for l in pages(key)[pn-1]['lines'] if y0<=l['bbox'][1]<y1)
  locations.append({'page':pn,'clip':list(rect)})
 return assets,'\n'.join(texts),locations

def single(key,pn):
 cached=OUT/'single-pages'/(key+'-'+digest_cached[key][:16])/f'{pn:03}.json'
 if cached.exists():return json.loads(cached.read_text(encoding='utf-8'))
 pg=pages(key)[pn-1];lines=[l for l in pg['lines'] if 45<l['bbox'][1]<pg['size'][1]-35 and not re.search('公众号|李林基础500',l['text'])]
 # OCR can miss formulas, so trim only the lower blank writing area, leaving generous padding.
 # A pixel projection preserves all visible content, even formula fragments absent in OCR.
 page=doc(key)[pn-1];pix=page.get_pixmap(matrix=fitz.Matrix(1,1));img=Image.frombytes('RGB',[pix.width,pix.height],pix.samples).convert('L')
 crop=img.crop((35,55,img.width-25,img.height-45));mask=crop.point(lambda p:255 if p<190 else 0);bbox=mask.getbbox()
 y1=min(page.rect.height-35,55+bbox[3]+16) if bbox else page.rect.height-35
 images,raw,loc=segment(key,{'page':pn,'y':50},{'page':pn,'y':y1+1},pn,True)
 cached.parent.mkdir(parents=True,exist_ok=True);cached.write_text(json.dumps([images,raw,loc],ensure_ascii=False),encoding='utf-8')
 return images,raw,loc

TOPICS=[
 ('奇偶性与周期性',r'奇函数|偶函数|奇偶性|周期函数|周期为','函数性质与定义','先按定义检查函数的奇偶性或周期性。',[]),
 ('数列极限与递推关系',r'数列|递推','数列极限与递推关系','先说明数列的递推条件和要判断的性质。',[]),
 ('曲率与弧长',r'曲率|弧长','曲率与弧长公式','先确认曲线的表示形式及适用公式。',[]),
 ('泰勒展开与等价无穷小',r'泰勒|等价无穷小|无穷小量', '比较首个非零项','先判断需要比较哪一阶？',['math2.limit.expansion_order','math2.limit.leading_term']),
 ('函数极限与连续性',r'极限|连续|间断|lim','极限与连续性判断','先判断极限的类型和成立条件。',['math2.limit.indeterminate']),
 ('曲线渐近线',r'渐近线','渐近线定义','先分别判断可能出现哪类渐近线。',[]),
 ('导数与微分',r'导数|可导|微分|求导','导数定义与求导法则','先说明函数与自变量的依赖关系。',['math2.derivative.chain']),
 ('中值定理与证明',r'罗尔|拉格朗日|柯西|中值定理','中值定理与辅助函数','先说明要证明的结论和可用条件。',[]),
 ('单调性与极值',r'单调|极值|极大|极小|最值|最小值|最大值','驻点与符号判别','先找需要检查的点与边界。',[]),
 ('不定积分与积分方法',r'不定积分|原函数|分部积分|换元|求积分','换元与分部积分','先判断积分结构适合哪种方法。',[]),
 ('定积分与积分应用',r'定积分|积分|面积|体积|旋转','积分区间与积分应用','先描述积分区域或所求几何量。',[]),
 ('反常积分',r'反常积分|广义积分|收敛|发散','反常积分与收敛性','先找可能引起反常的端点。',[]),
 ('多元函数微分学',r'偏导|全微分|隐函数|多元函数|二元函数','多元复合函数与隐函数求导','先说明变量之间的依赖关系。',['math2.derivative.chain']),
 ('二重积分',r'二重积分|积分区域|极坐标|累次积分','积分区域与次序转换','先用文字描述区域的边界。',[]),
 ('微分方程',r'微分方程|通解|特解|齐次.*方程','微分方程类型判断','先判断微分方程的类型和初始条件。',[]),
 ('行列式',r'行列式','行列式性质与展开','先观察可用的行列式性质。',[]),
 ('矩阵运算与秩',r'矩阵|伴随|逆矩阵|矩阵的秩|秩','矩阵运算与初等变换','先说明矩阵的条件和要求的量。',['math2.matrix.row_conditions']),
 ('向量与线性相关',r'向量|线性相关|线性无关|极大无关','向量组与线性关系','先区分线性相关条件与待求结论。',[]),
 ('线性方程组',r'线性方程组|基础解系|增广|解向量','秩与解的结构','先判断系数矩阵和增广矩阵的秩。',['math2.matrix.row_conditions']),
 ('特征值与相似对角化',r'特征值|特征向量|相似|对角化','特征值与相似变换','先明确特征值与矩阵条件的关系。',[]),
 ('二次型与正定性',r'二次型|正定|负定|惯性','二次型与合同变换','先写出对应对称矩阵并判断目标。',[])]
EXCLUDE=r'无穷级数|幂级数|级数的|级数收敛|收敛半径|收敛域|傅里叶|曲线积分|曲面积分|三重积分|散度|旋度|斯托克斯|高斯公式|方向导数|梯度'

def knowledge(qid,raw,answer,chapter,reference):
 hits=[t for t in TOPICS if re.search(t[1],flat(raw))]
 chapter_hits=[t for t in TOPICS if re.search(t[1],flat(chapter))]
 broad={'函数极限与连续性','定积分与积分应用','导数与微分','矩阵运算与秩'}
 hits=[t for t in hits if t[0] not in broad]+[t for t in chapter_hits if t[0] not in broad]+[t for t in hits if t[0] in broad]+[t for t in chapter_hits if t[0] in broad]
 hits=list({t[0]:t for t in hits}.values())
 if not hits:hits=[('数学二综合问题','','条件整理','先说说已知条件和你的解题思路。',[])]
 # The source's chapter narrows meaning; question-specific terms determine retrieval, not paper title.
 ordered=hits[:3];topic='、'.join(t[0] for t in ordered)
 methods=[{'name':t[2],'first_question':t[3],'checkpoints':[t[0]+'的适用条件','解释所选方法和关键变形，计算交给工具','对照原题检查定义域和结论']} for t in ordered[:2]]
 return {'question_id':qid,'question_text':('【本地 OCR 草稿，公式待核对】\n'+raw)[:30000] if raw.strip() else '请阅读下方原始题图，公式以图片为准。',
  'uncertain':True,'has_diagram':True,'topic':topic,'problem':{'kind':'scratch','skill_ids':list(dict.fromkeys(s for t in ordered for s in t[4]))[:6]},
  'methods':methods,'private_solution':('原书解析 OCR 草稿，公式必须对照参考解析图片核验：\n'+answer)[:9000] if reference else '',
  'rubric':'原书参考解析可供逐步核对。未人工核对结构化评分点时仅作参考估分，不冒充官方评分细则。',
  'warnings':['[local_ocr_only]','本地文本与 OCR 仅用于知识方向索引；首次练习须核对题图中的公式。'],
  'solution_basis':'reference' if reference else 'model_draft','reference_source':reference[:1000]}

def archive(key):
 filename=key+'-'+digest_cached[key][:12]+'.pdf';dest=UPLOADS/filename
 if not dest.exists():shutil.copy2(SOURCE/SOURCES[key],dest)
 return 'local-pdf-20261014/'+filename

PAPERS=[];QUESTIONS=[];EXCLUDED=[]
def addpaper(pid,title,key,warnings=None):
 PAPERS.append({'id':pid,'title':title,'subject':'数学二','filename':archive(key),'warnings':warnings or ['本地 PDF/OCR 导入，公式须以原图核对。']})

def addq(pid,n,key,assets,raw,loc,answer_key='',answer_assets=None,answer_raw='',answer_locs=None,chapter='',kind=None,max_points=1,points_known=False,reference_key=None,qid=None):
 qid=qid or pid+f'-q{int(n):03}'
 aa=answer_assets or [];al=answer_locs or [];source=(SOURCES[reference_key]+'；PDF 第 '+str(al[0]['page'])+' 页起') if reference_key and al else ''
 reference=('参考选项：'+answer_key+'。\n' if answer_key else '')+('已关联原书参考解析；公式以解析图片为准。\n'+source if aa else '')
 if not kind:kind='mcq' if all(x in raw for x in ['A','B','C','D']) else 'subjective'
 spec={'kind':kind,'max_points':max_points,'points_known':points_known,'answer_key':answer_key,'solution':reference,'source':source or '未提供可核对的逐题参考解析',
       'verified':False,'reference_images':aa,'reference_ocr_draft':True,'source_pdf':archive(key),'source_pages':loc,'source_question_number':str(n)}
 if source:spec['reference_pdf']=archive(reference_key)+'#page='+str(al[0]['page']);spec['reference_pages']=al
 if not aa:spec['reference_issue']='尚未可靠匹配本题解析，已保留原题；需核对来源后批改。'
 header=f'{chapter or "数学二"} · '+{'mcq':'选择题','fill':'填空题','subjective':'解答题'}[kind]+(f' · {max_points}分' if points_known else '')
 body=header+'\n请阅读下方原始题图，公式以图片为准。\n【本地 OCR 草稿，待核对】\n'+raw[:16000]
 QUESTIONS.append({'id':qid,'paper_id':pid,'number':str(n),'text':body,'images':assets,'reference_answer':reference,'subject':'数学二','confirmed':False,'spec':spec,
    'knowledge':knowledge(qid,raw,answer_raw,chapter,source)})

def mock_yu():
 qs=[4,12,20,28,36,44,52,60];ans=[7,18,30,42,53,66,79,94]
 for i in range(8):
  pid=f'local-yu-2027-math2-{i+1}';addpaper(pid,f'2027 张宇八套卷 · 数学二 · 第{i+1}套','yuq')
  qe=(qs+[68])[i+1]-2;ae=(ans+[107])[i+1]-1
  qa=anchors('yuq',qs[i],qe,22);aa=anchors('yua',ans[i],ae,22,True)
  for n in range(1,23):
   if n not in qa:continue
   qi,qt,ql=segment('yuq',qa[n],qa.get(n+1),qe,True)
   ai,at,al=segment('yua',aa.get(n),aa.get(n+1),ae)
   m=re.search(r'答案[】\]]?[（(]?([ABCD])[）)]?',flat(at[:120]));ak=m[1] if m and n<=10 else ''
   addq(pid,n,'yuq',qi,qt,ql,ak,ai,at,al,kind='mcq' if n<=10 else ('fill' if n<=16 else 'subjective'),max_points=5 if n<=16 else (10 if n==17 else 12),points_known=True,reference_key='yua')

def mock_ll():
 # Answers use three independent paper sequences in each of the two source volumes.
 for half,key in enumerate(['lla1','lla2']):
  pg=pages(key);starts=[1,13,24] if half==0 else [1,13,25]
  for j,start in enumerate(starts):
   idx=half*3+j;pid=f'local-lilin-2027-math2-{idx+1}';addpaper(pid,f'2027 李林六套卷 · 数学二 · 第{idx+1}套','llq')
   end=(starts+[len(pg)+1])[j+1]-1;aa=anchors(key,start,end,22,True)
   terminal=anchors(key,starts[j+1],min(len(pg),starts[j+1]+1),1,True).get(1) if j<2 else ({'page':36,'y':726} if key=='lla1' else None)
   for n in range(1,23):
    qi,qt,ql=single('llq',idx*22+n);ai,at,al=segment(key,aa.get(n),aa.get(n+1) or (terminal if n==22 else None),end)
    m=re.search(r'答案[】\]]?([ABCD])',flat(at[:130]));ak=m[1] if m and n<=10 else ''
    addq(pid,n,'llq',qi,qt,ql,ak,ai,at,al,kind='mcq' if n<=10 else ('fill' if n<=16 else 'subjective'),max_points=5 if n<=16 else (10 if n==17 else 12),points_known=True,reference_key=key)

CHAPTERS=['函数极限连续','一元函数微分学及其应用','一元函数积分学及其应用','多元函数微分学及其应用','二重积分','微分方程及其应用','行列式','矩阵','向量','线性方程组','相似矩阵','二次型']
BASE_Q_STARTS=[1,33,46,100,123,192,207,231,246,279,284,309,319,339,341,367,376,386,397,415,430,456,469,493,501]
BASE_A_STARTS=[4,13,17,32,40,61,66,72,77,86,89,96,100,106,108,114,117,121,124,128,132,138,142,147,151]
def base():
 solution_sections=[]
 for s in range(24):
  count=BASE_Q_STARTS[s+1]-BASE_Q_STARTS[s]
  solution_sections.append(anchors('basea',BASE_A_STARTS[s],min(BASE_A_STARTS[s+1],150),count,True))
 for ci,chapter in enumerate(CHAPTERS):
  pid=f'local-lilin-base500-math2-ch{ci+1:02}';addpaper(pid,f'李林基础500题 · 数学二 · 第{ci+1}章 {chapter}','baseq')
  for section in range(2):
   s=ci*2+section;start,end=BASE_Q_STARTS[s:s+2];count=end-start;astart,aend=BASE_A_STARTS[s:s+2];part='计算与方法篇' if not section else '概念与理解篇'
   aa=solution_sections[s]
   terminal=solution_sections[s+1].get(1) if s<23 else None
   for n,pn in enumerate(range(start,end),1):
    qi,qt,ql=single('baseq',pn);ai,at,al=segment('basea',aa.get(n),aa.get(n+1) or terminal,min(aend,150))
    m=re.search(r'(?:答案|选)[】\]]?[（(]?([ABCD])[）)]?',flat(at[:130]));kind='mcq' if all(x in qt for x in ['A','B','C','D']) else 'subjective';ak=m[1] if m and kind=='mcq' else ''
    addq(pid,n,'baseq',qi,qt,ql,ak,ai,at,al,chapter=chapter+' · '+part,kind=kind,reference_key='basea',qid=pid+f'-{section+1}-q{n:03}')

def selected():
 # Original book has 102 calculus, 31 linear algebra and 32 probability questions.
 for section,qs,qe,count,astart,aend,label in [('calc',4,54,102,2,54,'高等数学'),('linear',56,74,31,55,74,'线性代数')]:
  pid='local-selected-2025-math2-'+section;addpaper(pid,'往年模拟卷精选题 · 数学二适用 · '+label,'selq',['已排除概率与数一/数三专属知识方向；本地 OCR 公式待核对。'])
  qa=anchors('selq',qs,qe,count);aa=anchors('sela',astart,aend,count,True)
  for n in range(1,count+1):
   if n not in qa:continue
   qi,qt,ql=segment('selq',qa[n],qa.get(n+1),qe,True)
   ai,at,al=segment('sela',aa.get(n),aa.get(n+1),aend)
   scope=flat(qt)
   exclusion=re.search(EXCLUDE+r'|曲线积|差分方程|边际收益|数学[一三]单独|数学一[、,，]三|数学[一三][)）]|孝学一[)）]',scope) if section=='calc' else None
   if exclusion:EXCLUDED.append({'section':section,'number':n,'reason':exclusion[0],'source_pages':ql});continue
   addq(pid,n,'selq',qi,qt,ql,'',ai,at,al,chapter=label,reference_key='sela')
 EXCLUDED.append({'section':'probability','count':32,'reason':'概率论与数理统计不属于数学二'})

def main():
 mock_yu();mock_ll();base();selected()
 sources=[{'key':k,'filename':v,'sha256':digest_cached[k],'pages':len(pages(k))} for k,v in SOURCES.items()]
 manifest={'version':1,'sources':sources,'papers':PAPERS,'questions':QUESTIONS,'excluded':EXCLUDED,'issues':ISSUES,'classification':'数学二；本地目录/关键词分类，公式未确认；不调用远程模型'}
 path=OUT/'import-plan.json';path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'papers':len(PAPERS),'questions':len(QUESTIONS),'by_paper':dict(collections.Counter(q['paper_id'] for q in QUESTIONS)),'linked':sum(bool(q['spec']['reference_images']) for q in QUESTIONS),'issues':ISSUES,'excluded':EXCLUDED},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
