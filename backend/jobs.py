import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TIMEOUT=float(os.environ.get('MATHMASTER_TIMEOUT','15'))
SLOTS=threading.BoundedSemaphore(2)
class JobError(ValueError): pass


def run_job(operation,request,timeout=TIMEOUT):
    if not SLOTS.acquire(blocking=False): raise JobError('计算任务繁忙，请等待当前任务结束。')
    process=None
    try:
        process=subprocess.Popen([sys.executable,'-m','backend.worker'],cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            env={**os.environ,'PYTHONUTF8':'1'},start_new_session=os.name!='nt')
        try:
            stdout,_=process.communicate(json.dumps({'operation':operation,'request':request}),timeout=timeout)
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
