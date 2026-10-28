"""Structured, independently checked calculus rules for SymPy 1.14."""
import itertools
import sympy as s
from sympy.integrals.manualintegrate import integral_steps, manualintegrate
from sympy.calculus.util import continuous_domain
from .parser import parse, variable, MathInputError
from .formal import text as formal_text
from sympy.core.function import AppliedUndef


def equal(a,b):
    try:
        d=s.simplify(a-b)
        return d == 0 or d.is_zero is True
    except (NotImplementedError,ValueError,TypeError): return False

class Trace:
    def __init__(self):
        self.ids=itertools.count(1); self.warnings=[]; self.complete=True
    def step(self,rule,before,after,explanation,children=None,kind='equality',verified=None,**extra):
        if verified is None: verified=equal(before,after)
        return dict(step_id=f's{next(self.ids)}',rule=rule,before_latex=s.latex(before),
            after_latex=s.latex(after),explanation_zh=explanation,children=children or [],
            verified=bool(verified),verification=dict(kind=kind,before=str(before),after=str(after)),**extra)
    def primitive(self,rule,f,x,result,explanation,children=None,**extra):
        st=self.step(rule,s.Integral(f,x),result,explanation,children,'antiderivative',equal(s.diff(result,x),f),**extra)
        st['verification'].update(integrand=str(f),variable=str(x),derivative=str(s.diff(result,x)))
        return st

def response(op,inp,result,method,trace,verified,assumptions=None,**extra):
    approx=None
    if result is not None:
        try:
            if not getattr(result,'free_symbols',set()) and not result.has(s.Integral,s.Derivative,s.zoo,s.nan):
                approx=str(s.N(result,12))
        except (TypeError,AttributeError): pass
    return dict(operation=op,input_latex=s.latex(inp),result_latex=s.latex(result) if result is not None else '',
        exact_result=formal_text(result) if result is not None else None,approximate_result=approx,method=method,
        assumptions=assumptions or ['所有变量为实数；参数条件另行列出。'],steps=[],verified=bool(verified),
        warnings=list(dict.fromkeys(trace.warnings)),steps_complete=trace.complete,**extra)

FORMULAS={
 'PowerRule': ('幂函数积分',r'\int x^n\,dx=\frac{x^{n+1}}{n+1}\quad(n\ne-1)'),
 'ReciprocalRule': ('对数积分',r'\int \frac{1}{x}\,dx=\ln|x|'),
 'ConstantRule': ('常数积分',r'\int a\,dx=ax'),
 'ExpRule': ('指数函数积分',r'\int e^x\,dx=e^x'),
 'SinRule': ('正弦函数积分',r'\int\sin x\,dx=-\cos x'),
 'CosRule': ('余弦函数积分',r'\int\cos x\,dx=\sin x'),
 'ArctanRule': ('反正切积分',r'\int\frac{1}{1+x^2}\,dx=\arctan x'),
 'SecTanRule': ('三角函数积分',r'\int\sec x\tan x\,dx=\sec x'),
 'CscCotRule': ('三角函数积分',r'\int\csc x\cot x\,dx=-\csc x'),
}

def integral_trace(rule,tr,expected=None,depth=0):
    """Do not trust legacy context fields: ConstantTimesRule children may carry
    unscaled integrand metadata. Validate against the actual parent operand."""
    x=rule.variable; f=expected if expected is not None else rule.integrand
    name=type(rule).__name__
    if depth>18:
        tr.complete=False; tr.warnings.append('推导层级过深，已省略部分步骤。'); return []
    def sub(r,e=None): return integral_trace(r,tr,e,depth+1)
    if name=='AlternativeRule':
        choices=[r for r in rule.alternatives if not r.contains_dont_know()]
        return sub((choices or rule.alternatives)[0],f)
    if name=='DontKnowRule':
        tr.complete=False; tr.warnings.append('SymPy 无法提供该积分的完整手工推导；只展示可验证的结果。'); return []
    result=rule.eval()
    if name=='ConstantTimesRule':
        kids=sub(rule.substep,rule.other)
        inter=rule.constant*s.Integral(rule.other,x)
        st=tr.primitive('constant_multiple',f,x,inter,'先提出常数因子，保持积分的线性关系。',formula_latex=r'\int af(x)\,dx=a\int f(x)\,dx')
        kids.insert(0,st)
        return [tr.primitive(name,f,x,result,'将子积分的结果乘回常数。',kids)]
    if name=='AddRule':
        kids=[]
        for r in rule.substeps: kids+=sub(r)
        return [tr.primitive(name,f,x,result,'按积分的线性性质逐项积分，再相加。',kids,formula_latex=r'\int(f+g)\,dx=\int f\,dx+\int g\,dx')]
    if name=='RewriteRule':
        st=tr.step('algebraic_rewrite',f,rule.rewritten,'通过恒等变形或部分分式分解，将被积函数改写为容易积分的形式。')
        return [tr.primitive(name,f,x,result,'先验证变形前后等价，再积分。',[st]+sub(rule.substep,rule.rewritten))]
    if name=='URule':
        g=rule.u_func; u=rule.u_var; transformed=rule.substep.integrand
        reconstructed=transformed.subs(u,g)*s.diff(g,x)
        st=tr.step('substitution',s.Integral(f,x),s.Integral(transformed,u),
            '内函数的导数与被积式中的因子匹配，使用换元法。',kind='substitution',verified=equal(f,reconstructed),
            formula_latex=s.latex(s.Eq(s.Symbol('u'),g))+r',\quad du='+s.latex(s.diff(g,x))+r'\,d'+str(x))
        st['verification'].update(integrand=str(f),transformed=str(transformed),u=str(u),u_func=str(g),reconstructed=str(reconstructed))
        return [tr.primitive(name,f,x,result,'求出关于 u 的原函数后，将 u 换回原变量。',[st]+sub(rule.substep))]
    if name=='PartsRule' and rule.second_step is not None:
        v=rule.v_step.eval(); du=s.diff(rule.u,x); inter=rule.u*v-s.Integral(du*v,x)
        st=tr.primitive('parts_identity',f,x,inter,'乘积中一个因子求导后更简单，使用分部积分。',
            formula_latex=r'\int u\,dv=uv-\int v\,du',
            choices_latex=r'u='+s.latex(rule.u)+r',\quad dv='+s.latex(rule.dv)+r'\,d'+str(x)+r',\quad du='+s.latex(du)+r'\,d'+str(x)+r',\quad v='+s.latex(v))
        kids=sub(rule.v_step,rule.dv)+[st]+sub(rule.second_step,du*v)
        return [tr.primitive(name,f,x,result,'代入分部积分公式，计算剩余积分并整理。',kids)]
    if name in FORMULAS:
        label,formula=FORMULAS[name]
        # The template only claims the elementary base formula; parameters are in result.
        return [tr.primitive(name,f,x,result,f'识别为{label}形式，使用基本积分公式。',formula_latex=formula)]
    tr.complete=False
    tr.warnings.append(f'已得到结果，但 {name} 的详细中文推导暂未适配；不会补造步骤。')
    return [tr.primitive('verified_result',f,x,result,'仅展示经求导检查的原函数；这不是完整推导。')]

def all_verified(steps):
    return all(st['verified'] and all_verified(st['children']) for st in steps)


def integrate_job(req):
    tr=Trace(); x=variable(req.get('variable','x')); raw=parse(req['expression']); f=s.simplify(raw)
    if f.has(s.zoo,s.nan,s.oo,-s.oo): raise MathInputError('被积函数必须在定义域内为有限表达式。')
    primitive=s.integrate(f,x)
    tree=integral_steps(f,x)
    manual=manualintegrate(f,x)
    steps=integral_trace(tree,tr)
    # Suppress invalid rule metadata rather than turn a failed check into a plausible explanation.
    if not all_verified(steps):
        steps=[]; tr.complete=False
        tr.warnings.append('规则树的某个关系未通过校验，已隐藏不可靠推导，仅保留独立验证。')
    indefinite=not (req.get('lower') is not None and req.get('upper') is not None)
    if (req.get('lower') is None)!=(req.get('upper') is None): raise MathInputError('定积分必须同时填写上下限。')
    if indefinite:
        valid=not primitive.has(s.Integral) and equal(s.diff(primitive,x),f)
        if not manual.has(s.Integral) and not equal(s.diff(manual,x),f):
            tr.warnings.append('手工积分结果未通过验证，仅采用符号引擎结果。')
        steps.append(tr.primitive('verification',f,x,primitive,'独立验证：对最终答案求导，检查是否还原被积函数。'))
        if primitive.has(s.Integral): tr.warnings.append('尚未求出闭式原函数。'); tr.complete=False
        tr.warnings.append('原函数在各连通定义域上成立；对数、根号及符号参数需要检查定义域和分支，积分常数可因区间而异。')
        # Convert logarithmic primitives with constant coefficients into real
        # log|g| forms. Their derivatives agree on g != 0, even if function
        # values differ by a complex constant on a negative-sign component.
        analytic=primitive
        positive=s.Symbol('r',positive=True)
        real_logs=[]
        for term in analytic.atoms(s.log):
            g=term.args[0]; coefficient=s.expand(analytic).coeff(term)
            if g.is_real is True and g.is_positive is not True and coefficient and not coefficient.has(x):
                if equal(s.diff(s.log(s.Abs(positive)),positive),1/positive) and equal(-s.diff(s.log(s.Abs(-positive)),positive),-1/positive):
                    real_logs.append((term,s.log(s.Abs(g)),g))
        if real_logs:
            primitive=analytic.xreplace({old:new for old,new,_ in real_logs})
            conversion=tr.step('real_log_form',analytic,primitive,
                '对数项改写为实数形式 ln|g|。在 g≠0 的各连通区间，两式导数相同；原函数值可相差常数。',
                kind='real_log_conversion',verified=valid,
                formula_latex=r"(\ln|g(x)|)'=g'(x)/g(x)\quad(g(x)\ne0)")
            conversion['verification'].update(analytic=str(analytic),integrand=str(f),variable=str(x),
                arguments=[str(g) for _,_,g in real_logs],coefficients=[str(s.expand(analytic).coeff(old)) for old,_,_ in real_logs])
            steps.append(conversion)
        out=response('integrate',s.Integral(raw,x),primitive,'不定积分 · 手工规则树 + 求导验证',tr,valid)
        try:
            domain=continuous_domain(raw,x,s.S.Reals)
            out['assumptions'].append('实数定义域：'+s.latex(domain))
        except (NotImplementedError,ValueError):
            out['warnings'].append('未能完整求出实数定义域，需人工检查参数与分支条件。')
        if real_logs:out['assumptions'].extend(s.latex(g)+r'\ne0' for _,_,g in real_logs)
        out.update(steps=steps,result_latex=s.latex(primitive)+r' + C',exact_result=str(primitive)+' + C')
        return out
    a=s.simplify(parse(req['lower'])); b=s.simplify(parse(req['upper']))
    if a.free_symbols or b.free_symbols: raise MathInputError('当前定积分上下限需为明确实数或无穷大。')
    if a.is_extended_real is not True or b.is_extended_real is not True: raise MathInputError('积分上下限必须为实数。')
    if a in (s.oo,-s.oo) and a==b: raise MathInputError('无穷积分上下限不能相同。')
    inp=s.Integral(raw,(x,a,b)); sign=1
    if a>b: a,b=b,a; sign=-1
    if a==b: return dict(response('integrate',inp,s.S.Zero,'零长度积分',tr,True),steps=[])
    interval=s.Interval.open(a,b)
    try:
        domain=continuous_domain(raw,x,s.S.Reals)
        if interval.is_subset(domain) is not True:
            # Finite excluded points are explicitly split, not treated as principal values.
            missing=interval-domain
            if not isinstance(missing,s.FiniteSet):
                raise MathInputError('区间内存在非实数定义域或无法确定的奇点；请调整区间或分段计算。')
        singular=s.singularities(raw,x).intersect(interval)
    except NotImplementedError:
        raise MathInputError('无法可靠判定区间内定义域和奇点，请将积分拆成已知连续区间。')
    if singular is not s.S.EmptySet and not isinstance(singular,s.FiniteSet): raise MathInputError('存在无法枚举的奇点，暂不自动给出定积分结论。')
    points=[a]+sorted(singular,key=lambda q:float(q))+[b]
    vals=[]; direct_vals=[]; bounded_steps=[]; valid=True; divergent=False
    for lo,hi in zip(points,points[1:]):
        direct=s.integrate(raw,(x,lo,hi),conds='piecewise'); direct_vals.append(direct)
        if not primitive.has(s.Integral) and equal(s.diff(primitive,x),raw):
            left=s.limit(primitive,x,lo,dir='+'); right=s.limit(primitive,x,hi,dir='-')
            value=s.simplify(right-left)
            ok=value.is_finite is True and equal(value,direct)
            if left.is_finite is False or right.is_finite is False:
                divergent=True; ok=True
            st=tr.step('one_sided_limits',s.Integral(raw,(x,lo,hi)),value,
                '分别计算两端的单侧极限；仅当每段都收敛时才能相加。',kind='definite_limits',verified=ok,
                formula_latex=s.latex(right)+r'-\left('+s.latex(left)+r'\right)')
            st['verification'].update(primitive=str(primitive),lower=str(lo),upper=str(hi),left_limit=str(left),right_limit=str(right),sympy_result=str(direct))
            bounded_steps.append(st); vals.append(value); valid=valid and ok
        else:
            valid=False; tr.complete=False; vals.append(direct)
            tr.warnings.append('符号引擎返回了定积分结果，但未能完成独立的原函数极限验证。')
    if divergent or any(v.is_finite is False or v.has(s.zoo,s.nan) for v in vals):
        tr.warnings.append('该反常积分发散；两侧分别发散时不能以柯西主值代替普通积分。')
        out=response('integrate',inp,None,'分段反常积分 · 单侧极限',tr,valid,status='divergent')
        out.update(steps=bounded_steps,result_latex=r'\text{积分发散}',exact_result='divergent'); return out
    result=sign*s.Add(*vals)
    if singular: tr.warnings.append('已在每个内部奇点处分段，分别检查收敛。')
    if sign<0:
        bounded_steps.append(tr.step('reverse_bounds',s.Add(*vals),result,'原始上下限反向，结果取负。',kind='orientation',verified=equal(result,-s.Add(*vals))))
    out=response('integrate',inp,result,'定积分 · 定义域检查、分段与极限验证',tr,valid)
    out['steps']=steps+bounded_steps; return out


def derivative_trace(f,x,tr,depth=0):
    actual=s.diff(f,x); kids=[]; formula=None
    if depth>18:
        tr.complete=False
        return tr.step('symbolic_derivative',s.Derivative(f,x,evaluate=False),actual,'表达式过深，仅给出符号求导结果。',kind='derivative',verified=True)
    def sub(g): return derivative_trace(g,x,tr,depth+1)
    if not f.has(x): rule='constant'; rhs=s.S.Zero; explanation='对当前变量，常数和其他独立变量的导数为零。'
    elif f==x: rule='identity'; rhs=s.S.One; explanation='变量对自身的导数为 1。'
    elif f.is_Add:
        rule='sum'; kids=[sub(g) for g in f.args]; rhs=sum(s.diff(g,x) for g in f.args); explanation='按求导的线性性质逐项求导。'
    elif f.is_Mul:
        num,den=f.as_numer_denom()
        if den.has(x):
            rule='quotient'; kids=[sub(num),sub(den)]; rhs=(s.diff(num,x)*den-num*s.diff(den,x))/den**2
            formula=r'(u/v)^{\prime}=(u^{\prime}v-uv^{\prime})/v^2'; explanation='分母含当前变量，使用商法则；分母必须非零。'
        else:
            rule='product'; kids=[sub(g) for g in f.args if g.has(x)]
            rhs=sum(s.diff(g,x)*s.Mul(*(h for j,h in enumerate(f.args) if j!=i)) for i,g in enumerate(f.args))
            formula=r'(uv)^{\prime}=u^{\prime}v+uv^{\prime}'; explanation='使用乘积法则，每次只对一个因子求导。'
    elif f.is_Pow and not f.exp.has(x):
        base,n=f.args; rule='power' if base==x else 'chain'; rhs=n*base**(n-1)*s.diff(base,x)
        if base!=x: kids=[sub(base)]
        formula=r'(g(x)^n)^{\prime}=n g(x)^{n-1}g^{\prime}(x)'; explanation='使用幂函数公式；复合底数还需乘以内函数导数。'
    elif isinstance(f,s.Integral):
        rule='leibniz';rhs=actual
        explanation='使用变限积分求导公式：上限处被积函数乘上限导数，减去下限处被积函数乘下限导数；被积函数显含求导变量时另加积分项。'
    elif isinstance(f,AppliedUndef) and len(f.args)==1:
        inner=f.args[0];rule='chain';rhs=actual
        kids=[sub(inner)] if inner!=x else []
        explanation='未知一元函数保留形式导数，按链式法则乘以内函数导数；负自变量也必须保留符号。'
    elif f.func in (s.sin,s.cos,s.tan,s.cot,s.sec,s.csc,s.exp,s.log,s.asin,s.acos,s.atan,s.sinh,s.cosh,s.tanh):
        inner=f.args[0]; u=s.Dummy('u',real=True); outer=s.diff(f.func(u),u).subs(u,inner)
        rhs=outer*s.diff(inner,x); rule='chain' if inner!=x else f.func.__name__
        kids=[sub(inner)] if inner!=x else []
        formula=r'(f(g(x)))^{\prime}=f^{\prime}(g(x))g^{\prime}(x)'
        explanation='先对外函数求导，再乘以内函数导数。' if inner!=x else '使用该基本函数的求导公式。'
    else:
        rule='symbolic_derivative'; rhs=actual; explanation='符号引擎可以求导，但当前步骤规则没有完整展开此结构。'
        tr.complete=False; tr.warnings.append('部分求导步骤没有完整展开。')
    st=tr.step(rule,s.Derivative(f,x,evaluate=False),rhs,explanation,kids,kind='derivative',verified=equal(actual,rhs),formula_latex=formula)
    st['verification'].update(expression=str(f),variable=str(x),sympy_derivative=str(actual))
    return st


def differentiate_job(req, *, return_expression=False):
    from .formal import normalize_partials,FormalPartial
    tr=Trace(); f=s.simplify(parse(req['expression'],functions=req.get('functions'))); x=variable(req.get('variable','x'))
    if f.has(s.zoo,s.nan,s.oo,-s.oo):raise MathInputError('待求导函数不能包含无穷大或未定义常量。')
    order=req.get('order',1)
    if not isinstance(order,int) or not 1<=order<=8: raise MathInputError('导数阶数需为 1 到 8 的整数。')
    variables=req.get('variables') or [str(x)]*order
    if not isinstance(variables,list) or not 1<=len(variables)<=8: raise MathInputError('偏导变量序列最多 8 个。')
    current=f; steps=[]; vs=[variable(v) for v in variables]
    for v in vs:
        steps.append(derivative_trace(current,v,tr)); current=s.simplify(normalize_partials(s.diff(current,v)))
    check=f
    for v in vs:check=normalize_partials(s.diff(check,v))
    out=response('differentiate',s.Derivative(f,*vs,evaluate=False),current,'规则分解求导 + SymPy 交叉验证',tr,equal(current,check) and all_verified(steps))
    out['steps']=steps
    if f.has(AppliedUndef,s.Integral):out['warnings'].append('未知函数保留符号形式；变限积分需满足相应的连续性和可微条件，工具不额外假定奇偶性。')
    if current.has(FormalPartial):out['warnings'].append('多元未知函数的高阶偏导按相应阶数连续可微解释；未满足条件时不能据此交换混合偏导。')
    out['warnings'].append('公式在原函数可微的定义域内成立；分母非零，对数与根式需满足实数定义域。')
    return (out,current) if return_expression else out


def compute(operation,req):
    if operation=='integrate': return integrate_job(req)
    if operation=='differentiate': return differentiate_job(req)
    if operation=='matrix':
        from .matrix import matrix_job
        return matrix_job(req)
    raise MathInputError('不支持的操作。')
