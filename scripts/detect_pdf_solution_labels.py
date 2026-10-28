"""Detect colored reference labels locally; cache their geometry for verified associations."""
import concurrent.futures,json,sys
from pathlib import Path
from pdf_solution_labels import green
from prepare_local_pdf_library import OUT

def work(task):
 key,pn=task;dest=OUT/'labels'/key/f'{pn:03}.json'
 if dest.exists():return
 boxes=green(key,pn);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(boxes))
if __name__=='__main__':
 tasks=[(key,pn) for key,count in [('basea',150),('lla1',36),('lla2',37)] for pn in range(1,count+1)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
  for i,_ in enumerate(pool.map(work,tasks)):
   if i%30==0:print(i,flush=True)
