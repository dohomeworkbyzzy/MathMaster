"""Run with the environment being verified; does not modify the user's database."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.jobs import run_job
from backend.parser import parse
import sympy as s
checks=[]
for op,req,expected in [
 ('integrate',{'expression':'x*exp(x)'},'(x - 1)*exp(x) + C'),
 ('integrate',{'expression':'x^2','lower':'0','upper':'1'},'1/3'),
 ('differentiate',{'expression':'sin(x^2)'},'2*x*cos(x**2)'),
 ('matrix',{'matrix':[['0','1'],['2','3']],'action':'inverse'},'Matrix([[-3/2, 1/2], [1, 0]])')]:
    result=run_job(op,req)
    assert result['verified'],result
    assert result['exact_result']==expected,(expected,result['exact_result'])
    checks.append({'operation':op,'exact_result':result['exact_result'],'verified':result['verified']})
print(json.dumps({'python':sys.version.split()[0],'platform':sys.platform,'checks':checks},ensure_ascii=True))
