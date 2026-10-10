"""JSON-only process boundary; no pickle/untrusted objects."""
import json
import os
import sys

def main():
    if os.name!='nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(18,20))
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    from .engine import compute
    from .parser import MathInputError
    try:
        req=json.loads(sys.stdin.read(64000))
        out={'ok':True,'result':compute(req['operation'],req['request'])}
    except MathInputError as e: out={'ok':False,'error':str(e)}
    except Exception as e: out={'ok':False,'error':f'计算未完成（{type(e).__name__}）；请简化表达式或检查定义域。'}
    sys.stdout.write(json.dumps(out,ensure_ascii=False))

if __name__=='__main__': main()
