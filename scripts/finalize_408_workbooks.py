"""Join generated answer evidence into the reviewed image bank, retaining uncertain questions."""
import argparse,collections,csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/408-workbooks'

def finalize(require_all=True):
 paths=sorted([*(OUT/'plans').glob('*.json'),*(OUT/'plans').glob('*.pending'),*(OUT/'plans').glob('*.native')]);plans=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
 if len(plans)!=8 or any(not p['papers'][0]['id'].endswith('-v3') for p in plans):raise ValueError('8 份最终拆题计划尚未就绪')
 result={k:[item for p in plans for item in p[k]] for k in ('papers','questions','issues')};review=[];missing=[];by_paper=collections.defaultdict(collections.Counter)
 for q in result['questions']:
  path=OUT/'answers'/(q['id']+'.json');count=by_paper[q['paper_id']];count['questions']+=1
  if not path.exists():missing.append(q['id']);continue
  a=json.loads(path.read_text(encoding='utf-8'))
  if a['id']!=q['id']:raise ValueError('答案 ID 不匹配')
  key=a['answer_key'];uncertain=a['uncertain'] or not key
  label='AI 生成，待核对（不是原书答案）'
  solution=label+'\n'+(('候选答案：' if uncertain else '参考答案：')+key if key else '暂无可确定的参考选项，请对照原图核对。')
  reasons=a.get('uncertainties',[])
  if reasons:solution+='\n待复核：'+'；'.join(reasons)
  if not re.fullmatch(r'[ABCD]',key) and key:q['spec']['kind']='subjective'
  q['reference_answer']=solution
  q['spec'].update(answer_key=key,solution=solution,answer_origin='ai_generated',verified=False,answer_model=a['model_id'],answer_generated_at=a['generated_at'],answer_uncertain=uncertain,source=label+'；模型 '+a['model_id']+'；'+q['spec']['source'])
  if uncertain:
   q['spec']['reference_issue']='AI 解题存在不确定性，请先核对题干与答案，再人工评分。'+('；'.join(reasons))
   review.append({'id':q['id'],'paper':q['paper_id'],'number':q['number'],'source_number':q['spec']['source_number'],'pdf_page':q['spec']['source_locations'][0]['page'],'candidate':key,'reason':'；'.join(reasons) or a['explanation']});count['needs_review']+=1
  else:q['spec'].pop('reference_issue',None);count['answered']+=1
 if missing and require_all:raise ValueError(f'仍有 {len(missing)} 题未生成答案')
 stats={'papers':len(result['papers']),'questions':len(result['questions']),'generated':len(result['questions'])-len(missing),'answered':sum(c['answered'] for c in by_paper.values()),'needs_review':len(review),'not_generated':len(missing),'by_paper':dict(by_paper),'missing_ids':missing}
 (OUT/'import-plan-answers.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
 (OUT/'answer-report.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
 with (OUT/'needs-review.csv').open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=['id','paper','number','source_number','pdf_page','candidate','reason']);writer.writeheader();writer.writerows(review)
 print(json.dumps({k:v for k,v in stats.items() if k not in ('by_paper','missing_ids')},ensure_ascii=False),flush=True)
 return stats
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--allow-partial',action='store_true');a=p.parse_args();finalize(not a.allow_partial)
