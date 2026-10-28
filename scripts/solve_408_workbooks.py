"""Resumeable image-grounded 408 answer generation using the locally configured provider."""
import argparse,base64,concurrent.futures,io,json,os,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from backend.ai import provider
OUT=ROOT/'artifacts/408-workbooks';ANSWERS=OUT/'answers'
SYSTEM='''你是严谨的考研408四科教师。逐题独立解题，核对题干、所有选项、图表、单位与计算，然后输出答案和可复查的中文解析。图片是原题，OCR仅作辅助；优先按图片纠正OCR错误。不能因为OCR错误、图表缺失而猜选项。遇到题干/选项不全、辨认不清、歧义或你不能可靠解决的题，answer_key留空，uncertain=true并说明原因，禁止编造确定答案。注意题目要求选正确还是错误、多项命题组合；解析要给出推理/计算和关键排除理由，通常100-350字。答案不是原书标准答案，始终是待核对的生成稿。仅输出JSON对象 {"answers":[{"id":"原ID","answer_key":"单空A/B/C/D，多空按空号依次连接字母如CB，或空","explanation":"解析","uncertain":false,"uncertainties":[]}]}，每道原题恰好一项；含多组编号选项的多空题须回答全部空，answer_key按空号依次连接字母，例如CB，解析中逐空注明。若原题采用I、II等罗马编号或是多选/多空组合，answer_key按原题标签列出各组答案，不强行转成A/B/C/D。'''

def validate(content,ids):
 value=provider.json_content(content);rows=value['answers']
 if isinstance(rows,list):
  if len(ids)==1 and len(rows)==1 and isinstance(rows[0],dict):rows[0]['id']=ids[0]
  else:
   for row in rows:
    suffix=re.search(r'q[0-9]{4}$',str(row.get('id','')))
    matches=[qid for qid in ids if suffix and qid.endswith(suffix[0])]
    if len(matches)==1:row['id']=matches[0]
  for row in rows:
   if row.get('answer_key') is None:row['answer_key']='';row['uncertain']=True
   if isinstance(row.get('answer_key'),str):
    key=row['answer_key'].strip()
    row['answer_key']=re.sub(r'[\s,，、;；/]+','',key).upper() if re.fullmatch(r'[ABCDabcd\s,，、;；/]*',key) else key
   if 'uncertain' not in row:row['uncertain']=True
   if 'uncertainties' not in row:row['uncertainties']=[]
   if row.get('uncertainties') is None:row['uncertainties']=[]
 if not isinstance(rows,list) or len(rows)!=len(ids) or {r['id'] for r in rows}!=set(ids):raise ValueError('答案 ID 不匹配')
 for r in rows:
  if not isinstance(r['answer_key'],str) or len(r['answer_key'])>1000 or not isinstance(r['uncertain'],bool) or not isinstance(r['explanation'],str) or not r['explanation'].strip():raise ValueError('答案格式不完整')
  if not isinstance(r.get('uncertainties'),list) or any(not isinstance(v,str) for v in r['uncertainties']):raise ValueError('不确定性字段无效')
  if not r['answer_key'] and not r['uncertain']:raise ValueError('无答案必须标记待复核')
 return rows

def solve(batch,profile):
 ids=[q['id'] for q in batch];content=[]
 for q in batch:
  content.append({'type':'text','text':'题目 ID：'+q['id']+'\nOCR文字：\n'+q['text'][:14000]})
  for name in q['images']:
   with Image.open(ROOT/'data/uploads'/name) as im:
    im=im.convert('RGB');im.thumbnail((1024,1600));buf=io.BytesIO();im.save(buf,'JPEG',quality=88)
   content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()}})
 last=''
 for attempt in range(2):
  try:
   r=provider.request_profile(profile,[{'role':'system','content':SYSTEM},{'role':'user','content':content}],cache_kind='workbook408',validator=lambda s:validate(s,ids))
   if r.get('finish_reason')=='length':raise ValueError('输出截断')
   rows=validate(r['content'],ids)
   for answer in rows:
    answer.update(model_id=r['model_id'],answer_origin='ai_generated',verified=False,usage=r.get('usage',{}),generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    target=ANSWERS/(answer['id']+'.json');tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(target)
   return {'ok':len(rows),'uncertain':sum(r['uncertain'] for r in rows),'usage':r.get('usage',{}),'cache_hit':r.get('cache_hit')}
  except (ValueError,OSError,KeyError,TypeError) as exc:
   last=str(exc)
   if any(t in last for t in ['401','402','403','404','429','密钥','配置','不支持']):break
   if attempt==0:time.sleep(2)
 return {'ok':0,'failed':ids,'error':last[:300]}

def main():
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=6);p.add_argument('--batch-size',type=int,default=4);p.add_argument('--limit',type=int,default=0);p.add_argument('--watch',action='store_true');p.add_argument('--plan-glob',default='*.json');a=p.parse_args()
 profile=provider.load_profile().model_copy(deep=True);profile.timeout=max(profile.timeout,180)
 # Avoid truncating a multi-question explanation; never modify the saved user profile.
 profile.extra_body={**profile.extra_body,'max_tokens':14000}
 ANSWERS.mkdir(parents=True,exist_ok=True)
 print('model',profile.model_id,'workers',a.workers,'batch_size',a.batch_size,flush=True)
 tried=set();results=[];total_ok=0
 while True:
  plans=[path for path in (OUT/'plans').glob(a.plan_glob) if json.loads(path.read_text(encoding='utf-8'))['papers'][0]['id'].endswith('-v3')];questions=[q for path in sorted(plans) for q in json.loads(path.read_text(encoding='utf-8'))['questions']]
  todo=[q for q in questions if not (ANSWERS/(q['id']+'.json')).exists() and q['id'] not in tried]
  if a.limit:todo=todo[:max(0,a.limit-total_ok)]
  if todo:
   batches=[todo[i:i+a.batch_size] for i in range(0,len(todo),a.batch_size)]
   with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
    futures=[pool.submit(solve,b,profile) for b in batches]
    for f in concurrent.futures.as_completed(futures):
     result=f.result();results.append(result);total_ok+=result['ok']
     if result.get('failed'):tried.update(result['failed'])
     print(json.dumps({'completed_this_run':total_ok,'available_questions':len(questions),'answer_files':len(list(ANSWERS.glob('*.json'))),'result':result},ensure_ascii=False),flush=True)
     (OUT/'solve-progress.json').write_text(json.dumps({'completed_this_run':total_ok,'available_questions':len(questions),'batches':results},ensure_ascii=False),encoding='utf-8')
     if result.get('failed') and any(t in result['error'] for t in ['401','402','403','404','密钥','配置']):raise SystemExit('模型接口不可用，停止新增调用；已生成答案保留。')
  if a.limit and total_ok>=a.limit:break
  if not a.watch or (OUT/'layout-complete.json').exists() and len(plans)==8:break
  time.sleep(10)
 print('finished',total_ok,'failed',len(tried),flush=True)
if __name__=='__main__':main()
