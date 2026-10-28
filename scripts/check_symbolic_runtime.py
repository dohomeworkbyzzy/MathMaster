"""Exercise the packaged Windows tool worker with the reported integral."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import socket,tempfile,time,urllib.request,shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import sympy as s
from backend.parser import parse


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,default=ROOT/'artifacts/calculus-build/master')
    args=parser.parse_args()
    exe=args.runtime.resolve()/'master.exe'
    integral='integrate(phi(t)+phi(-t),(t,x-y,x+y))'
    pure="phi'(x+y)-phi'(-x-y)-phi'(x-y)+phi'(y-x)"
    mixed="phi'(x+y)-phi'(-x-y)+phi'(x-y)-phi'(y-x)"
    def call(tool,request):
        result=subprocess.run([str(exe),'--ai-worker'],input=json.dumps({'operation':tool,'request':request}).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        assert result.returncode==0,result.stderr.decode('utf8',errors='replace')[-1000:]
        payload=json.loads(result.stdout)
        assert payload['ok'],payload
        return payload['result']
    for variables,expected in ((['x','x'],pure),(['y','y'],pure),(['x','y'],mixed),(['y','x'],mixed)):
        result=call('math.differentiate',{'expression':integral,'variables':variables})
        assert result['verified'] and s.simplify(parse(result['exact_result'])-parse(expected))==0
    wrong=mixed.replace("phi'(-x-y)","phi'(-x+y)")
    result=call('math.check_derivative',{'expression':integral,'variables':['x','y'],'proposed':wrong})
    assert result['verdict']=='not_equal' and result['counterexample']['left']!=result['counterexample']['right']
    result=call('math.check_derivative',{'expression':integral,'variables':['x','y'],'proposed':mixed})
    assert result['verdict']=='symbolically_equal_on_common_domain'
    assert call('math.differentiate',{'expression':'u(x+y)'})['exact_result']!='u'
    result=call('math.verify_step',{'expression':'phi(sqrt(x-y))','proposed':'phi(x)'})
    assert result['counterexample'] is None
    cases=[('f(x*x,y*y)',['x','y'],'4*x*y*partial(f(x*x,y*y),1,2)'),
           ('f(x,x)',['x'],'partial(f(x,x),1)+partial(f(x,x),2)'),
           ('f(x,x)',['x','x'],'partial(f(x,x),1,1)+2*partial(f(x,x),1,2)+partial(f(x,x),2,2)')]
    for expression,variables,expected in cases:
        result=call('math.check_derivative',{'expression':expression,'variables':variables,'proposed':expected})
        assert result['verified'],result
        reused=call('math.transform',{'expression':result['exact_result']})
        assert s.simplify(parse(reused['exact_result'])-parse(expected))==0
    result=call('math.differentiate',{'expression':r'\varphi^{\prime}(x)'})
    assert s.simplify(parse(result['exact_result'])-parse("phi''(x)"))==0
    result=call('math.differentiate',{'expression':'integrate(phi(x),x)'})
    assert result['exact_result']=='phi(x)'
    result=call('math.transform',{'expression':'f(x)','action':'substitute','value':'psi(y)','functions':['psi']})
    assert result['exact_result']=='f(psi(y))'
    result=call('math.check_derivative',{'expression':'f(x+y,x-y,x*y)','variables':['x','y'],'proposed':'diff(f(x+y,x-y,x*y),x,y)'})
    assert result['verified']
    # Start the packaged HTTP service against an isolated, empty data folder.
    (ROOT/'.test-data').mkdir(exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='symbolic-http-',dir=ROOT/'.test-data'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    (temporary/'config.json').write_text(json.dumps({'host':'127.0.0.1','port':port,'public_origins':[],'background_indexing':False}))
    process=subprocess.Popen([str(exe),'--root',str(temporary)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base=f'http://127.0.0.1:{port}'
        deadline=time.monotonic()+40
        while True:
            try:
                with opener.open(base+'/api/health',timeout=1) as response:
                    assert json.load(response)['status']=='ok'
                break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        request=urllib.request.Request(base+'/api/math/differentiate',data=json.dumps({'expression':integral,'variables':['x','y'],'functions':['phi']}).encode(),headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=30) as response:
            result=json.load(response)
        assert result['verified'] and s.simplify(parse(result['exact_result'])-parse(mixed))==0
        with opener.open(base+'/assets/MathMasterTouchpad.zip',timeout=10) as response:
            assert response.read(2)==b'PK'
    finally:
        subprocess.run([str(exe),'--root',str(temporary),'--stop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        process.wait(timeout=25)
        shutil.rmtree(temporary,ignore_errors=True)
    print(json.dumps({'frozen_symbolic_worker':True,'original_integral_partials':4,'wrong_and_correct_checks':True,'unknown_function_semantics':True,'counterexample_domains':True,'multivariate_partials_and_reuse':True,'latex_primes':True,'indefinite_integral_reuse':True,'custom_functions':True,'frozen_http_api':True,'helper_download':True}))


if __name__=='__main__':main()
