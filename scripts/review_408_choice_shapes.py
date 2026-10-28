"""Re-evaluate non-single choice output where the source does not explicitly provide multiple answer groups."""
import concurrent.futures,json,re,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import solve_408_workbooks as solver
OUT=ROOT/'artifacts/408-workbooks'
solver.SYSTEM+='\n复核要求：严格按原图判断单选、多选或多空。若题目是单选而你认为多个选项合理，不要随意输出组合字母，应将uncertain设为true并说明歧义。answer_key必须与解析最后明确选择的选项一致。不要把题中罗马编号的陈述当成多个待填写的空。'

def main():
 sys.stdout.reconfigure(encoding='utf-8');profile=solver.provider.load_profile().model_copy(deep=True);profile.timeout=180;profile.extra_body={**profile.extra_body,'max_tokens':8000}
 qs=[q for p in (OUT/'plans').glob('*.json') for q in json.loads(p.read_text(encoding='utf-8'))['questions']];todo=[]
 for q in qs:
  a=json.loads((OUT/'answers'/(q['id']+'.json')).read_text(encoding='utf-8'))
  if not a['answer_key'] or re.fullmatch('[ABCD]',a['answer_key']):continue
  raw=q['text'];groups=len(re.findall(r'(?:^|\n)(?:[（(]\d+[)）])?\s*A[.．]',raw))
  explicit_multi=groups>1 or '多选' in raw or sum(ch in raw for ch in '①②③④⑤')>=2
  if explicit_multi:continue
  backup=OUT/'answer-revisions'/(q['id']+'-before-choice-shape-review.json')
  if not backup.exists():shutil.copyfile(OUT/'answers'/(q['id']+'.json'),backup)
  todo.append(q)
 print('reviewing',len(todo),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for i,result in enumerate(pool.map(lambda q:solver.solve([q],profile),todo),1):print(i,result,flush=True)
 # No non-single draft is promoted to an automatic single-choice reference.
 for q in todo:
  path=OUT/'answers'/(q['id']+'.json');a=json.loads(path.read_text(encoding='utf-8'))
  if a['answer_key'] and not re.fullmatch('[ABCD]',a['answer_key']):
   a['uncertain']=True;a['uncertainties']=list(dict.fromkeys(a.get('uncertainties',[])+['单选题仍存在多个候选选项，请人工核对。']))
  a['choice_shape_reviewed']=True;path.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
 print('review complete',len(todo),flush=True)
if __name__=='__main__':main()
