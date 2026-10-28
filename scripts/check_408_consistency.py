"""Read-only comparison of answers to exactly matching question text and option order."""
import collections,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/408-workbooks'

def normalized(q):
 text=q['text']
 if ' · PDF 第 ' in text:text=text.split(' · PDF 第 ',1)[-1].split('\n',1)[-1]
 elif q['id'].startswith('real-408-'):text=text.split('\n',1)[-1]
 if re.search('[\ue000-\uf8ff]',text):return None
 text=re.sub(r'^[（(]?\d+[）).．、]?\s*','',text)
 text=re.sub(r'^[【\[(（]+[Pp]\s*\d+[】\]）)1 ]*','',text)
 text=re.sub(r'【\s*\d{4}[^】]*】','',text)

 lines=[l for l in text.splitlines() if not re.match(r'^\d+\.\d+|^第\s*\d+\s*章|^公众号|^速刷|^OS 速刷',l.strip())]
 value=re.sub(r'[^\w\u4e00-\u9fff<>=+*/^%→-]+','',''.join(lines))
 return value if len(value)>=60 else None

def main():
 paths=[*(OUT/'plans').glob('*.json'),*(OUT/'plans').glob('*.pending'),*(OUT/'plans').glob('*.native')]
 groups=collections.defaultdict(list)
 for path in paths:
  for q in json.loads(path.read_text(encoding='utf-8'))['questions']:
   key=normalized(q)
   if key:groups[key].append(q)
 goldens=collections.defaultdict(list)
 for ref in json.loads((OUT/'existing-references.json').read_text(encoding='utf-8')):
  norm=normalized(ref)
  if norm:goldens[norm].append(ref)
 duplicates=[];conflicts=[];matched=[];reference_conflicts=[]
 for key,qs in groups.items():
  refs=goldens.get(key,[])
  if refs and len({r['answer_key'] for r in refs})==1:
   for q in qs:
    path=OUT/'answers'/(q['id']+'.json')
    if path.exists():
     a=json.loads(path.read_text(encoding='utf-8'));match={'id':q['id'],'generated_answer':a['answer_key'],'reference_answer':refs[0]['answer_key'],'reference_id':refs[0]['id'],'reference_source':refs[0]['source']}
     matched.append(match)
     if a['answer_key']!=refs[0]['answer_key']:reference_conflicts.append(match)
  if len(qs)<2:continue
  rows=[]
  for q in qs:
   path=OUT/'answers'/(q['id']+'.json')
   if path.exists():
    a=json.loads(path.read_text(encoding='utf-8'));rows.append({'id':q['id'],'answer':a['answer_key'],'uncertain':a['uncertain']})
  if len(rows)<2:continue
  duplicates.append(rows)
  if len({r['answer'] for r in rows if not r['uncertain']})>1:conflicts.append(rows)
 result={'exact_duplicate_groups':len(duplicates),'compared_questions':sum(len(g) for g in duplicates),'conflicts':conflicts,'reference_matches':matched,'reference_conflicts':reference_conflicts,'method':'Exact normalized stem and option text in source order; formulas with private-use glyphs excluded.'}
 (OUT/'consistency-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({**result,'reference_matches':len(matched)},ensure_ascii=False))
if __name__=='__main__':main()
