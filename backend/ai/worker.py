"""JSON-only process boundary; no pickle/untrusted objects."""
import json
import os
import sys

def main():
    if os.name!='nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(18,20))
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    from .registry import compute
    from ..parser import MathInputError
    try:
        req=json.loads(sys.stdin.buffer.read(64000).decode('utf-8'))
        out={'ok':True,'result':compute(req['operation'],req['request'])}
    except MathInputError as e: out={'ok':False,'error':str(e)}
    except Exception as e: out={'ok':False,'error':f'计算未完成（{type(e).__name__}）；请简化表达式或检查定义域。'}
    sys.stdout.buffer.write(json.dumps(out,ensure_ascii=False).encode('utf-8'))

if __name__=='__main__': main()
