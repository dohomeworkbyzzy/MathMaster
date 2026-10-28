"""Keep machine-readable choices consistent with the model's explicit final conclusion; retain revisions."""
import json,re,shutil
from datetime import datetime,timezone
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'artifacts/408-workbooks'
revisions=OUT/'answer-revisions';revisions.mkdir(exist_ok=True)
records=[];nonstandard=[]
for p in (OUT/'answers').glob('*-v3-*.json'):
 a=json.loads(p.read_text(encoding='utf-8'))
 matches=list(re.finditer(r'(?:故选|应选|因此选|选项为|对应选项|答案[是为：:]|正确答案[是为：:])\s*[：:]?\s*([ABCD])',a['explanation']))
 if matches and len(a['answer_key'])==1 and matches[-1][1]!=a['answer_key']:
  before=a['answer_key'];after=matches[-1][1]
  backup=revisions/(p.stem+'-before-conclusion-reconciliation.json')
  if not backup.exists():shutil.copyfile(p,backup)
  a.update(answer_key=after,format_review={'method':'align_structured_choice_with_explicit_final_conclusion','before':before,'after':after,'at':datetime.now(timezone.utc).isoformat()})
  p.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8');records.append({'id':a['id'],'before':before,'after':after})
 if a['answer_key'] and not re.fullmatch('[ABCD]',a['answer_key']):nonstandard.append({'id':a['id'],'answer':a['answer_key'],'uncertain':a['uncertain']})
(OUT/'choice-format-review.json').write_text(json.dumps({'corrected':records,'nonstandard_choices':nonstandard},ensure_ascii=False,indent=2),encoding='utf-8')
print('Aligned choices',len(records),'Nonstandard choices',len(nonstandard))
