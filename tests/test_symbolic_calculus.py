import pytest
import sympy as s
from backend.parser import parse,MathInputError
from backend.ai.registry import compute
from backend.ai import adaptive

INTEGRAL='integrate(phi(t)+phi(-t),(t,x-y,x+y))'
WRONG="phi'(x+y)-phi'(-x+y)+phi'(x-y)-phi'(y-x)"
MIXED="phi'(x+y)-phi'(-x-y)+phi'(x-y)-phi'(y-x)"
PURE="phi'(x+y)-phi'(-x-y)-phi'(x-y)+phi'(y-x)"

@pytest.mark.parametrize('variables,expected',[
    (['x'], 'phi(x+y)+phi(-x-y)-phi(x-y)-phi(y-x)'),
    (['y'], 'phi(x+y)+phi(-x-y)+phi(x-y)+phi(y-x)'),
    (['x','x'], PURE), (['y','y'], PURE), (['x','y'], MIXED), (['y','x'], MIXED),
])
def test_original_variable_limit_integral_keeps_the_signs_and_only_needs_first_phi_derivative(variables,expected):
    result=compute('math.differentiate',{'expression':INTEGRAL,'variables':variables})
    actual=parse(result['exact_result'])
    assert s.simplify(actual-parse(expected))==0
    assert result['verified'] and result['result_latex']
    if len(variables)==2:
        assert actual.atoms(s.Derivative)
        assert all(len(d.variables)==1 for d in actual.atoms(s.Derivative))
    assert any(step['rule']=='leibniz' for step in result['steps'])
    # A separate concrete calculation checks against the explicit antiderivative.
    x,y=s.symbols('x y',real=True);phi=s.Function('phi')
    concrete=actual.replace(phi,lambda t:t**2).doit()
    polynomial=4*x*x*y+s.Rational(4,3)*y**3
    assert s.simplify(concrete-s.diff(polynomial,*[{'x':x,'y':y}[v] for v in variables]))==0


def test_derivative_check_refutes_the_reported_expression_with_a_legal_counterexample():
    result=compute('math.check_derivative',{'expression':INTEGRAL,'variables':['x','y'],'proposed':WRONG})
    assert result['verdict']=='not_equal' and not result['verified']
    witness=result['counterexample']
    assert witness['functions']=={'phi(t)':'t**2'}
    assert witness['left']!=witness['right']
    result=compute('math.check_derivative',{'expression':INTEGRAL,'variables':['x','y'],'proposed':MIXED})
    assert result['verdict']=='symbolically_equal_on_common_domain' and result['verified']


def test_unknown_function_is_never_silently_treated_as_a_constant_multiplier():
    result=compute('math.differentiate',{'expression':'u(x+y)'})
    assert s.simplify(parse(result['exact_result'])-parse("u'(x+y)"))==0
    assert result['exact_result']!='u'
    custom=compute('math.differentiate',{'expression':'psi(x-y)','functions':['psi'],'variables':['y']})
    assert s.simplify(parse(custom['exact_result'],functions=['psi'])+parse("psi'(x-y)",functions=['psi']))==0
    # Explicit multiplication retains its original meaning.
    assert compute('math.differentiate',{'expression':'u*(x+y)'})['exact_result']=='u'


@pytest.mark.parametrize('notation',["phi'(x+y)","varphi'(x+y)","φ′(x+y)","ϕ'(x+y)",r"\varphi'(x+y)"])
def test_phi_aliases_primes_and_roundtrip(notation):
    assert s.simplify(parse(notation)-parse("phi'(x+y)"))==0
    result=compute('math.differentiate',{'expression':notation,'variables':['x']})
    assert s.simplify(parse(result['exact_result'])-parse("phi''(x+y)"))==0


@pytest.mark.parametrize('expression',[
    "integrate(__import__('os'),(t,0,1))",'integrate(f(t))','integrate(f(t),(t,0))',
    'integrate(f(t),(t,0,oo))','integrate(f(t),(t,t,x))','integrate(f(t),(t,0,1),(x,0,1))',
    'diff(f(x),__import__)','diff(f(x),x).doit()',"f'''''''''(x)","f'(x,y)",
    'f(x)+f(x,y)', 'integrate(f(t),(t,0,1)) trailing',
])
def test_extended_grammar_remains_closed(expression):
    with pytest.raises(MathInputError):parse(expression)


def test_higher_partials_pass_the_ai_schema_and_worker_boundary(tmp_path,monkeypatch):
    from backend import db
    from backend.ai.jobs import run_job
    monkeypatch.setattr(db,'DATA',tmp_path)
    result=run_job('math.differentiate',{'expression':INTEGRAL,'variables':['x','y']})
    assert result['verified'] and s.simplify(parse(result['exact_result'])-parse(MIXED))==0


def test_conditional_check_blocks_followup_derivatives_after_failure_and_does_not_promote_self_correction(monkeypatch):
    called=[]
    def run(tool,args,**kw):
        called.append(tool)
        return {'verdict':'not_equal','exact_result':PURE,'result_latex':'x'}
    monkeypatch.setattr(adaptive,'run_job',run)
    replies=iter([
        {'tool_calls':[{'tool':'math.check_derivative','input':{'expression':INTEGRAL,'variables':['x','y'],'proposed':WRONG}},
                       {'tool':'math.differentiate','input':{'expression':INTEGRAL,'variables':['x','x']}},
                       {'tool':'math.check_derivative','input':{'expression':INTEGRAL,'variables':['x','y'],'proposed':MIXED}}]},
        {'message':'第二项自变量的负号需要修正，先停在当前核对。'}])
    monkeypatch.setattr(adaptive,'model_reply',lambda *a,**kw:(adaptive.Reply.model_validate(next(replies)),{'model_id':'fixture','usage':{}}))
    question={'id':'fixture','kind':'scratch','subject':'math2','text':'核对变限积分','images':[],'skills':[]}
    text="请检查我算的偏导对不对，如果对再把其他偏导算出来，"+WRONG
    assert adaptive.conditional_derivative_check(text)
    _,message,cards,meta=adaptive.run(question,adaptive.initial(question),text,[],[])
    assert called==['math.check_derivative'] and len(cards)==1
    assert '先停' in message
    assert len(meta['tool_errors'])==2


def test_conditional_check_permits_requested_calculation_only_after_success(monkeypatch):
    called=[]
    def run(tool,args,**kw):
        called.append(tool)
        return {'verdict':'symbolically_equal_on_common_domain','exact_result':PURE,'result_latex':'x'}
    monkeypatch.setattr(adaptive,'run_job',run)
    replies=iter([
        {'tool_calls':[{'tool':'math.check_derivative','input':{'expression':INTEGRAL,'variables':['x','y'],'proposed':MIXED}},
                       {'tool':'math.differentiate','input':{'expression':INTEGRAL,'variables':['x','x']}}]},
        {'message':'当前混合偏导核对通过，已按委托列出另一项供比对。'}])
    monkeypatch.setattr(adaptive,'model_reply',lambda *a,**kw:(adaptive.Reply.model_validate(next(replies)),{'model_id':'fixture','usage':{}}))
    q={'id':'fixture','kind':'scratch','subject':'math2','text':'变限积分','images':[],'skills':[]}
    text='请检查我的导数，如果正确再帮我算其他二阶偏导'
    adaptive.run(q,adaptive.initial(q),text,[],[])
    assert called==['math.check_derivative','math.differentiate']


def test_counterexample_does_not_sample_unverified_root_or_pole_domains():
    from backend.formal import counterexample
    assert counterexample(parse('phi(sqrt(x-y))'),parse('phi(x)')) is None
    assert counterexample(parse('phi(x)/(x-y)'),parse('phi(x)')) is None


@pytest.mark.parametrize('expression',['f(x+y,y)','f(x*x,y*y)','f(sin(x),cos(y))','f(x,x)'])
@pytest.mark.parametrize('variables',[['x'],['x','x'],['x','y'],['y','x']])
def test_multivariate_chain_rule_preserves_argument_positions_and_can_be_reused(expression,variables):
    from backend.formal import FormalPartial
    x,y=s.symbols('x y',real=True)
    a,b=s.symbols('a b')
    polynomial=a**3*b**2+a*b
    def concrete(expr):
        def substitute(node):
            fn,indices=node.args
            return s.diff(polynomial,*[(a,b)[int(k)] for k in indices]).subs(dict(zip((a,b),fn.args)),simultaneous=True)
        return expr.replace(lambda node:isinstance(node,FormalPartial),substitute).replace(s.Function('f'),lambda u,v:polynomial.subs({a:u,b:v},simultaneous=True)).doit()
    result=compute('math.differentiate',{'expression':expression,'variables':variables})
    # Differentiate an explicit polynomial independently, rather than asking
    # the same unknown-function CAS path to verify itself.
    expected=s.diff(concrete(parse(expression)),*[{'x':x,'y':y}[v] for v in variables])
    assert s.simplify(concrete(parse(result['exact_result']))-expected)==0
    checked=compute('math.check_derivative',{'expression':expression,'variables':variables,'proposed':result['exact_result']})
    assert checked['verified']
    reused=compute('math.differentiate',{'expression':result['exact_result'],'variables':['x']})
    assert s.simplify(concrete(parse(reused['exact_result']))-s.diff(expected,x))==0


@pytest.mark.parametrize('notation',[r'\varphi^{\prime}(x)',r'\phi^\prime(x)',r'f^{\prime\prime}(x)',"f^{''}(x)"])
def test_raised_latex_primes_are_derivatives(notation):
    expected="phi'(x)" if 'phi' in notation else "f''(x)"
    assert s.simplify(parse(notation)-parse(expected))==0


def test_substitution_keeps_declared_function_names():
    result=compute('math.transform',{'expression':'f(x)','action':'substitute','value':'psi(y)','functions':['psi']})
    assert result['exact_result']=='f(psi(y))'


@pytest.mark.parametrize('expression',['integrate(', 'integrate(f(t),(', 'integrate(f(t),(t,0,1)', 'diff(', 'partial(', 'partial(f(x,y),)', 'partial(f(x,y),3)', 'partial(f(x,y),1', 'partial(f(x,y),0)'])
def test_truncated_constructors_report_math_input_errors(expression):
    with pytest.raises(MathInputError):parse(expression)


@pytest.mark.parametrize('functions',[[[]],{},'psi',[None],['partial']])
def test_bad_function_declarations_report_math_input_errors(functions):
    with pytest.raises(MathInputError):parse('x',functions=functions)

@pytest.mark.parametrize('text',['检查我的导数对不对','先核对这个偏导，核验通过后再计算其他项','请检查我的偏导，如果\n正确再算其他项','不要先计算其他的，检查我的导数对不对'])
def test_check_requests_authorize_verification_even_without_help_me(text):
    assert adaptive.calculation_requested(text)
    if '通过后' in text or '如果' in text:assert adaptive.conditional_derivative_check(text)

def test_unresolved_indefinite_integral_can_be_reused_and_differentiated():
    from backend.formal import text
    x=s.Symbol('x',real=True)
    integral=s.Integral(s.Function('phi')(x),x)
    assert parse(text(integral))==integral
    result=compute('math.differentiate',{'expression':text(integral)})
    assert result['exact_result']=='phi(x)'
    nested=s.Integral(s.Function('f')(x),x,s.Symbol('y',real=True))
    assert parse(text(nested))==nested

@pytest.mark.parametrize('expression',['f(x,x,x)','f(x,y,x+y)'])
def test_three_argument_functions_keep_all_partial_positions(expression):
    from backend.formal import FormalPartial
    x,y=s.symbols('x y',real=True);a,b,c=s.symbols('a b c')
    polynomial=a**2*b+b**3*c+a*c**2
    def concrete(expr):
        def replace(node):
            fn,indices=node.args
            return s.diff(polynomial,*[(a,b,c)[int(k)] for k in indices]).subs(dict(zip((a,b,c),fn.args)),simultaneous=True)
        return expr.replace(lambda node:isinstance(node,FormalPartial),replace).replace(s.Function('f'),lambda u,v,w:polynomial.subs({a:u,b:v,c:w},simultaneous=True)).doit()
    for variables in [['x','x'],['x','y']]:
        result=compute('math.differentiate',{'expression':expression,'variables':variables})
        expected=s.diff(concrete(parse(expression)),*[{'x':x,'y':y}[v] for v in variables])
        assert s.simplify(concrete(parse(result['exact_result']))-expected)==0

def test_derivative_check_does_not_reparse_its_own_expanded_output_with_user_input_limits():
    result=compute('math.check_derivative',{'expression':'f(x+y,x-y,x*y)','variables':['x','y'],'proposed':'diff(f(x+y,x-y,x*y),x,y)'})
    assert result['verified']
    with pytest.raises(MathInputError):parse(result['exact_result'])
