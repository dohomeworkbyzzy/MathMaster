"""Independent mathematical checks; no production parsing of SymPy strings."""
import pytest
import sympy as s
from backend.engine import compute
from backend.parser import parse, parse_equation, MathInputError

x,y=s.symbols('x y',real=True)

def run(expression,**kwargs):
    return compute('differentiate',dict(expression=expression,mode='implicit',**kwargs))

def flatten(steps):
    for step in steps:
        yield step
        yield from flatten(step['children'])

@pytest.mark.parametrize('expression,expected',[
    ('x^2+y^2=1',-x/y),('x^3+y^3=3*x*y',(y-x*x)/(y*y-x)),
    ('sin(x*y)=x+y',(1-y*s.cos(x*y))/(x*s.cos(x*y)-1)),
    ('exp(y)+x*y=2',-y/(x+s.exp(y))),
    ('log(x+y)=x-y',(x+y-1)/(x+y+1)),
    ('sin(x+y^2)+y=0',-s.cos(x+y*y)/(2*y*s.cos(x+y*y)+1)),
    ('x/y+y=2',-y/(y*y-x)),('y^2=x',1/(2*y)),
    (r'\frac{x^2}{4}+y^2=1',-x/(4*y)),('x^2+y^2-1',-x/y)])
def test_implicit_results_and_trace(expression,expected):
    out=run(expression)
    assert out['verified'] and out['steps_complete'] and out['status']=='conditional'
    got=s.sympify(out['exact_result'],locals={'x':x,'y':y})
    assert s.simplify(got-expected)==0
    lhs,rhs=parse_equation(expression); f=lhs-rhs
    assert s.simplify(s.idiff(f,y,x)-got)==0
    assert s.simplify(s.diff(f,x)+s.diff(f,y)*got)==0
    rules={st['rule'] for st in flatten(out['steps'])}
    assert {'implicit_rearrange','implicit_chain','implicit_collect','implicit_solve','implicit_simplify','implicit_verification','dependent_variable'}<=rules
    assert all(st['verified'] for st in flatten(out['steps']))
    # Check the actual chain-rule equations independently, including y(x).
    local={'x':x,'y':s.Function('y')}
    for st in flatten(out['steps']):
        v=st['verification']
        if v['kind']=='derivative':
            assert s.simplify(s.diff(s.sympify(v['expression'],locals=local),x)-s.sympify(v['after'],locals=local))==0
        if st['rule']=='implicit_verification':assert s.sympify(v['residual'])==0
    assert any('C¹' in a for a in out['assumptions'])
    assert any(r'\ne0' in a for a in out['assumptions'])

def test_other_variable_direction():
    out=run('t^2+z^2=1',variable='t',dependent_variable='z')
    assert out['verified'] and s.simplify(parse(out['exact_result'])+parse('t/z'))==0

def test_regular_point():
    out=run('x^2+y^2=1',point={'x':'3/5','y':'4/5'})
    assert out['exact_result']=='-3/4' and out['verified']
    assert out['steps'][-1]['rule']=='implicit_point'

@pytest.mark.parametrize('expression,point,status',[
    ('x^2+y^2=1',{'x':'1','y':'0'},'no_finite_derivative'),
    ('y^2=x',{'x':'0','y':'0'},'no_finite_derivative'),
    ('y^3=x^3',{'x':'0','y':'0'},'undetermined'),
    ('y^2=x^2',{'x':'0','y':'0'},'undetermined'),
    ('y^2=0',None,'conditional'),('x=0',None,'no_finite_derivative'),
    ('0=0',None,'undetermined')])
def test_special_points_do_not_divide_by_zero(expression,point,status):
    out=run(expression,**({'point':point} if point is not None else {}))
    assert out['status']==status
    if status!='conditional':
        assert out['exact_result'] is None and not out['verified'] and not out['steps_complete']

def test_unexpanded_trace_is_not_failure_to_differentiate():
    out=run('x^x+y=1')
    assert out['verified'] and not out['steps_complete'] and out['exact_result'] is not None
    assert s.simplify(parse(out['exact_result'])+x**x*(s.log(x)+1))==0
    assert any('没有完整展开' in w for w in out['warnings'])

@pytest.mark.parametrize('expression,kwargs',[
    ('x^2+y^2=1',{'variable':'y'}),('x+y+z=1',{}),
    ('x+y=1',{'order':2}),('x+y=1',{'order':True}),
    ('x+y=1',{'variables':['x']}),('x+y=1',{'variables':[]}),
    ('x=y=1',{}),('x==y',{}),('=y',{}),('x=',{}),('x<=y',{}),
    ('x=y;1',{}),("x=__import__('os')",{}),('x=oo',{}),
    ('x+y=1',{'point':{'x':'0'}}),('x+y=1',{'point':{'x':'0','y':'0'}}),
    ('x+y=1',{'point':{'x':'a','y':'1'}}),
    ('x+y=1',{'point':{'x':'oo','y':'1'}}),
    ('x/x+y=1',{'point':{'x':'0','y':'0'}}),
    ('log(x/x)+y=x',{'point':{'x':'0','y':'0'}}),
    ('sqrt(x/x)+y=1',{'point':{'x':'0','y':'0'}}),
    ('sqrt(-1)+y=0',{}),('log(0)+y=0',{}),
    ('log(x)+y=0',{'point':{'x':'-1','y':'0'}}),
    ('sqrt(y)=x',{'point':{'x':'0','y':'0'}}),
])
def test_invalid_inputs_and_domain(expression,kwargs):
    with pytest.raises(MathInputError):run(expression,**kwargs)

def test_expression_parser_stays_closed():
    with pytest.raises(MathInputError):parse('x=y')

def test_failed_independent_verification_is_not_a_false_answer(monkeypatch):
    monkeypatch.setattr(s,'idiff',lambda *args: s.Integer(123))
    out=run('x^2+y^2=1')
    assert out['status']=='unverified' and out['exact_result'] is None and not out['verified']
