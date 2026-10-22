"""First-order implicit differentiation without solving for a branch of y."""
import sympy as s
from .parser import parse, parse_equation, variable, MathInputError
from .engine import Trace, response, equal, derivative_trace, all_verified


def implicit_differentiate_job(req):
    if type(req.get('order',1)) is not int or req.get('order',1)!=1 or req.get('variables') is not None:
        raise MathInputError('隐函数模式仅支持一阶求导，不能同时指定混合偏导变量序列。')
    x=variable(req.get('variable','x')); y=variable(req.get('dependent_variable','y'))
    if x==y: raise MathInputError('自变量和因变量必须不同。')
    lhs,rhs=parse_equation(req['expression'])
    if (lhs.free_symbols|rhs.free_symbols)-{x,y}:
        raise MathInputError('当前隐函数模式仅支持所选的两个变量，不支持额外参数。')
    if any(v.has(s.zoo,s.nan,s.oo,-s.oo) for v in (lhs,rhs)):
        raise MathInputError('方程不能包含无穷大或未定义常量。')
    raw=s.Add(lhs,-rhs,evaluate=False); f=s.simplify(raw)
    if f.has(s.zoo,s.nan,s.oo,-s.oo) or any(
        not node.free_symbols and (node.is_real is False or node.is_finite is False)
        for node in s.preorder_traversal(raw)):
        raise MathInputError('方程包含未定义或非实数常量，请检查实数定义域。')
    fx=s.simplify(s.diff(f,x)); fy=s.simplify(s.diff(f,y))
    tr=Trace(); steps=[]; equation=s.Eq(lhs,rhs,evaluate=False)
    assumptions=['所有变量为实数；须满足原方程及原始表达式的实数定义域（化简不扩大定义域）。',
                 '在所考察点的邻域内，原关系 F 的一阶偏导数须连续（C¹）。',
                 s.latex(s.Eq(f,0,evaluate=False)),s.latex(fy)+r'\ne0']
    tr.warnings.append('Fy≠0 是此公式适用的充分条件，并非可微的必要条件；Fy=0 时不能直接用该公式判断导数不存在。')
    if raw.has(s.Abs):
        tr.warnings.append('含绝对值：须另行检查折点；符号结果仅在原关系满足 C¹ 条件的区域使用。')

    # Keep the unsimplified operands for point-domain checks, including removable holes.
    point=req.get('point'); substitutions=None
    if point is not None:
        if not isinstance(point,dict) or set(point)!={str(x),str(y)}:
            raise MathInputError('点坐标必须恰好包含自变量和因变量。')
        substitutions={v:s.simplify(parse(point[str(v)])) for v in (x,y)}
        if any(v.free_symbols or v.is_real is not True or v.is_finite is not True for v in substitutions.values()):
            raise MathInputError('点坐标必须是明确的有限实数。')
        for node in s.preorder_traversal(raw):
            value=node.subs(substitutions,simultaneous=True)
            if value.is_real is not True or value.is_finite is not True:
                raise MathInputError('该点不在原始表达式可确认的实数定义域内。')
        if not equal(raw.subs(substitutions,simultaneous=True),0):
            raise MathInputError('给定点不满足原方程。')
        assumptions.append('点坐标：'+', '.join(f'{v}={value}' for v,value in substitutions.items()))

    def relation(rule,before,after,explanation,ok,**extra):
        return tr.step(rule,before,after,explanation,kind='implicit_relation',verified=ok,**extra)
    steps.append(relation('implicit_rearrange',equation,s.Eq(f,0,evaluate=False),
        '将右侧移到左侧，记 F=左侧−右侧；保留原方程的定义域限制。',equal(raw,f)))
    yfun=s.Function(str(y))(x); lifted=raw.subs(y,yfun)
    chain=derivative_trace(lifted,x,tr,dependent=yfun)
    derivative=s.diff(lifted,x); p=s.Symbol(str(y)+"'")
    total=derivative.subs(s.diff(yfun,x),p).subs(yfun,y)
    collected=fx+fy*p
    steps.append(relation('implicit_chain',s.Eq(s.Derivative(lifted,x,evaluate=False),0,evaluate=False),
        s.Eq(total,0,evaluate=False),'把因变量看成函数，逐项使用乘积法则和链式法则。',
        equal(total,collected),children=[chain],formula_latex=r'\frac{dF}{d'+str(x)+r'}=F_'+str(x)+r'+F_'+str(y)+r'\frac{d'+str(y)+r'}{d'+str(x)+r'}=0'))
    steps.append(relation('implicit_collect',s.Eq(total,0,evaluate=False),
        s.Eq(fy*p,-fx,evaluate=False),'合并含因变量导数的项，再将其余项移到右侧。',equal(total,collected)))

    at_fy=fy if substitutions is None else s.simplify(fy.subs(substitutions,simultaneous=True))
    if substitutions is not None:
        partials=[v.subs(substitutions,simultaneous=True) for v in (fx,fy)]
        if any(v.is_real is not True or v.is_finite is not True for v in partials):
            raise MathInputError('该点的偏导数无法确认为有限实数，当前 C¹ 隐函数公式不适用；不能据此断言导数不存在。')
    if at_fy.is_zero is True:
        tr.complete=False
        assumptions.remove(s.latex(fy)+r'\ne0')
        assumptions.append('此处 Fy=0，不满足导数公式的除法条件；只分析一阶关系。')
        at_fx=fx if substitutions is None else s.simplify(fx.subs(substitutions,simultaneous=True))
        status='no_finite_derivative' if at_fx.is_zero is False else 'undetermined'
        tr.warnings.append('Fy=0 且 Fx≠0：在 C¹ 条件下不存在有限的因变量导数。' if status=='no_finite_derivative'
                           else 'Fy=0 且一阶关系退化：当前方法无法判定，需分析分支或使用更高阶信息；不代表不能求导。')
        out=response('differentiate',equation,None,'一阶隐函数求导 · 特殊点分析',tr,False,assumptions,
                     status=status,mode='implicit')
        out.update(steps=steps,result_latex=r'\text{'+('不存在有限导数（须满足 C¹）' if status=='no_finite_derivative' else '当前方法无法判定')+'}')
        return out

    result=s.simplify(-fx/fy)
    # Independent route: SymPy's implicit differentiation, plus total-derivative residual.
    try:
        reference=s.idiff(f,y,x)
        verified=equal(result,reference) and equal(total.subs(p,result),0)
    except (ValueError,NotImplementedError,TypeError):
        reference=None; verified=False
    if result.has(s.Derivative,s.zoo,s.nan,s.oo,-s.oo):
        verified=False
    if not verified:
        tr.complete=False; tr.warnings.append('未能通过 SymPy 独立验证，不展示未经验证的导数。')
        out=response('differentiate',equation,None,'一阶隐函数求导 · 验证未完成',tr,False,assumptions,status='unverified',mode='implicit')
        out.update(steps=steps,result_latex=r'\text{结果验证未完成}'); return out
    quotient=-fx/fy
    steps.append(relation('implicit_solve',s.Eq(fy*p,-fx,evaluate=False),s.Eq(p,quotient,evaluate=False),
        '在所列条件下除以 F 的因变量偏导数，得到导数公式。',equal(fy*quotient,-fx)))
    steps.append(tr.step('implicit_simplify',quotient,result,'化简导数，原方程的定义域与非零条件仍然保留。'))
    check=relation('implicit_verification',result,reference,
        '独立调用 SymPy idiff，并把导数代回全微分关系，残差应为零。',verified)
    check['verification'].update(expression=str(f),variable=str(x),dependent_variable=str(y),
                                 residual=str(s.simplify(total.subs(p,result))),sympy_result=str(reference))
    steps.append(check)
    if substitutions is not None:
        value=s.simplify(result.subs(substitutions,simultaneous=True))
        if value.is_real is not True or value.is_finite is not True:
            raise MathInputError('无法确认该点的导数为有限实数，请检查光滑性和定义域。')
        steps.append(tr.step('implicit_point',result,value,'代入点坐标；仍须检查该点邻域内的 C¹ 条件。',
                             kind='point_substitution',verified=equal(result.subs(substitutions,simultaneous=True),value)))
        result=value
    if not all_verified(steps):
        steps=[]; tr.complete=False; tr.warnings.append('部分推导未通过检查，已隐藏；最终结果已通过独立验证。')
    out=response('differentiate',equation,result,'一阶隐函数求导 · 链式法则 + SymPy idiff 独立验证',tr,True,
                 assumptions,status='conditional',mode='implicit')
    out.update(steps=steps,result_latex=r'\frac{d'+str(y)+r'}{d'+str(x)+r'}='+s.latex(result))
    return out
