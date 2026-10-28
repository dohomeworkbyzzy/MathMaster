import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from ..runtime import ROOT, worker_command
from . import cache
from .schemas import SCHEMAS
import hashlib

def _tool_version():
    import sympy
    digest=hashlib.sha256(('tools-v3-symbolic-calculus:'+sympy.__version__+':'+str(sys.version_info[:2])).encode())
    for relative in ('ai/registry.py','ai/schemas.py','ai/cs.py','ai/series_match.py','parser.py','formal.py','engine.py','matrix.py'):
        source=Path(__file__).resolve().parents[1]/relative
        if source.is_file():digest.update(source.read_bytes())
    return digest.hexdigest()

TOOL_VERSION=_tool_version()

TIMEOUT=float(os.environ.get('MATHMASTER_AI_TIMEOUT','15'))
SLOTS=threading.BoundedSemaphore(2)
class JobError(ValueError): pass


def run_job(operation,request,timeout=TIMEOUT,cancelled=None):
    if operation not in SCHEMAS:raise JobError('工具未注册。')
    try:request=SCHEMAS[operation].model_validate(request).model_dump(exclude_none=True)
    except ValueError:raise JobError('计算参数无效，请检查表达式与字段。') from None
    identity=cache.key({'version':TOOL_VERSION,'tool':operation,'input':request})
    with cache.single_flight('tools',identity,cancelled,JobError):
        value=cache.get('tools',identity)
        if value is not None:return {**value,'cache_hit':True}
        generation=cache.generation()
        value=_run_job(operation,request,timeout,cancelled)
        if cancelled and cancelled():raise JobError('本轮计算已取消。')
        cache.put('tools',identity,value,180*86400,generation)
        return {**value,'cache_hit':False}

def _run_job(operation,request,timeout,cancelled):
    if not SLOTS.acquire(blocking=False): raise JobError('计算任务繁忙，请等待当前任务结束。')
    process=None
    try:
        process=subprocess.Popen(worker_command('backend.ai.worker'),cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            env={**os.environ,'PYTHONUTF8':'1'},start_new_session=os.name!='nt',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            if cancelled is None:
                stdout,_=process.communicate(json.dumps({'operation':operation,'request':request}),timeout=timeout)
            else:
                deadline=time.monotonic()+timeout
                payload=json.dumps({'operation':operation,'request':request})
                while True:
                    if cancelled():
                        process.kill();process.communicate()
                        raise JobError('本轮计算已取消，工作进程已回收。')
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise subprocess.TimeoutExpired(process.args,timeout)
                    try:
                        stdout,_=process.communicate(payload,timeout=min(.1,remaining))
                        break
                    except subprocess.TimeoutExpired:
                        payload=None
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise JobError('计算超时，工作进程已终止。请简化表达式或缩小矩阵。')
        if process.returncode!=0: raise JobError('计算达到资源限制或进程退出，请简化输入。')
        if len(stdout)>2_000_000: raise JobError('计算结果过大，请简化输入。')
        out=json.loads(stdout)
        if not out['ok']: raise JobError(out['error'])
        return out['result']
    finally:
        if process and process.poll() is None: process.kill(); process.wait()
        SLOTS.release()
