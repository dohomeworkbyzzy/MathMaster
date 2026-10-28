"""Build/reuse all durable knowledge vectors using the selected embedding profile."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import db
from backend.ai import knowledge,vectors,profiles

if __name__=='__main__':
    db.init_db();knowledge.init();vectors.init();profiles.initialize()
    started=time.perf_counter();qs=vectors.all_questions()
    print('questions',len(qs),flush=True)
    result=vectors.index_questions(qs,progress=lambda n:print('indexed',n,flush=True))
    print(json.dumps({**result,'seconds':round(time.perf_counter()-started,2),'status':vectors.stats()},ensure_ascii=False),flush=True)
