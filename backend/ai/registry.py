import sympy as s
from .schemas import SCHEMAS
from ..parser import parse, variable, MathInputError
from ..engine import compute as legacy_compute,differentiate_job
from ..formal import text as formal_text,counterexample


def point_value(text, finite=False):
    p = s.simplify(parse(text))
    if p.free_symbols or p.is_extended_real is not True or (finite and p.is_finite is not True):
        raise MathInputError('趋近点必须是明确实数；泰勒展开只支持有限点。')
    return p


def sides(f, x, p, direction):
    if p in (s.oo, -s.oo):
        return [s.limit(f, x, p)]
    dirs = ['-', '+'] if direction == 'both' else ['-' if direction == 'left' else '+']
    return [s.limit(f, x, p, dir=d) for d in dirs]


def pack(expr, **extra):
    return {'exact_result': formal_text(expr), 'result_latex': s.latex(expr), **extra}


def check_identity(f,g):
    diff=s.simplify(f-g)
    verdict='symbolically_equal_on_common_domain' if diff==0 else ('not_equal' if diff.is_zero is False else 'undetermined')
    witness=counterexample(f,g) if verdict=='undetermined' else None
    if witness:verdict='not_equal'
    return {'verdict':verdict,'counterexample':witness,'relation':'identity_on_common_domain',
            'verification_status':'symbolic_check','warnings':['仅核验公共定义域上的表达式相等；不自动证明两式定义域相同。']}


def cache(q):
    scale = {'B': 1, 'KiB': 1024, 'MiB': 1024**2}
    cap = q['data_capacity'] * scale[q['capacity_unit']]
    block = q['block_size'] * scale[q['block_unit']]
    unit = 1 if q['addressing_unit'] == 'byte' else q['word_bytes']
    def bits(n):
        if n < 1 or n & (n - 1):
            raise MathInputError('块内寻址单元数、组数及路数必须为 2 的整数次幂。')
        return n.bit_length() - 1
    bits(q['ways'])
    if block % unit or cap % (block * q['ways']):
        raise MathInputError('容量必须能整除块大小×路数，块大小必须能整除寻址单位。')
    sets = cap // (block * q['ways'])
    offset, index = bits(block // unit), bits(sets)
    tag = q['address_bits'] - offset - index
    if tag < 0: raise MathInputError('地址宽度不足以容纳偏移和索引。')
    result = {}
    if q['stage'] in ('offset', 'all'): result.update(offset=offset, addressable_units_per_block=block // unit)
    if q['stage'] in ('index', 'all'): result.update(index=index, sets=sets)
    if q['stage'] in ('tag', 'all'): result.update(tag=tag)
    address = q.get('address')
    if address is not None:
        if address >= 2**q['address_bits']: raise MathInputError('地址超出指定宽度。')
        if q['stage'] in ('offset','all'): result['address_offset'] = address % (2**offset)
        if q['stage'] in ('index','all'): result['address_index'] = (address >> offset) % sets
        if q['stage'] in ('tag','all'): result['address_tag'] = address >> (offset + index)
    return {'fields': result, 'relation': 'address_bit_partition',
            'assumptions': ['容量仅包含数据，不含 tag、有效位等元数据。'], 'verification_status': 'integer_arithmetic_checked'}


def compute(tool, request):
    if tool not in SCHEMAS: raise MathInputError('工具未注册。')
    q = SCHEMAS[tool].model_validate(request).model_dump(exclude_none=True)
    if tool=='math.check_derivative':
        derivative,expected=differentiate_job({key:value for key,value in q.items() if key!='proposed'},return_expression=True)
        proposed=parse(q['proposed'],functions=q.get('functions'))
        checked=check_identity(expected,proposed)
        return {**derivative,**checked,'operation':'check_derivative',
                'verified':checked['verdict']=='symbolically_equal_on_common_domain',
                'proposed_latex':s.latex(proposed),
                'warnings':derivative['warnings']+checked['warnings']}
    if tool=='math.solve':
        names={v:s.Symbol(v,real=True) for v in q['variables']+q['parameters']}
        variables=[names[v] for v in q['variables']]
        equations=[]
        for equation in q['equations']:
            if equation.count('=')!=1:raise MathInputError('方程需要恰好一个等号，如 a+1=0。')
            left,right=equation.split('=')
            equations.append(parse(left,symbols=names)-parse(right,symbols=names))
        unknowns=set().union(*(e.free_symbols for e in equations))-set(names.values())
        if unknowns:raise MathInputError('当前方程含未指定参数，请明确所有待求变量或先代入已知量。')
        solutions=s.solve(equations,variables,dict=True)
        if len(solutions)>32:raise MathInputError('解的数量过多，请缩小方程组。')
        checked=[]
        for solution in solutions:
            if all(s.simplify(e.subs(solution))==0 for e in equations):checked.append(solution)
        denominators={s.factor(s.denom(s.cancel(value))) for sol in checked for value in sol.values()}
        conditions=sorted({str(s.factor(factor))+' != 0' for den in denominators if den!=1 for factor in s.Mul.make_args(den) if factor.free_symbols})
        return {'solutions':[{str(k):str(v) for k,v in sol.items()} for sol in checked],
                'solutions_latex':[{s.latex(k):s.latex(v) for k,v in sol.items()} for sol in checked],
                'assumptions':conditions,
                'verification_status':'substitution_checked','relation':'equation_solutions',
                'warnings':(['仅在原方程定义域及所列分母非零条件下成立；参数特殊取值可能需要另行讨论。'] if conditions else []) if checked else ['未求出可核验的解；不代表已证明无解。']}
    if tool in ('cs.page_replacement','cs.graph','cs.subnet'):
        from . import cs
        return {'cs.page_replacement':cs.replacement,'cs.graph':cs.graph,'cs.subnet':cs.subnet}[tool](q)
    if tool == 'math.series_match':
        from .series_match import compute as match
        return match(q)
    if tool == 'cs.cache_address': return cache(q)
    if tool in ('math.integrate', 'math.differentiate', 'math.matrix'):
        return legacy_compute(tool.split('.')[1], q)
    x = variable(q.get('variable','x'))
    if tool == 'math.lhopital_step':
        p = point_value(q['point'])
        n, d = parse(q['numerator']), parse(q['denominator'])
        ns, ds = sides(n,x,p,q['direction']), sides(d,x,p,q['direction'])
        admissible = all((a == 0 and b == 0) or (a in (s.oo,-s.oo) and b in (s.oo,-s.oo)) for a,b in zip(ns,ds))
        if not admissible: raise MathInputError('当前形式不是已确认的 0/0 或无穷/无穷型，不能作洛必达变换。')
        dn, dd = s.diff(n,x), s.diff(d,x)
        if dd == 0: raise MathInputError('分母导数恒为零，不满足洛必达条件。')
        return pack(dn/dd, numerator=str(dn), denominator=str(dd),
                    operation='differentiate_numerator_denominator', relation='conditional_limit_transformation',
                    condition_note=q['condition_note'], verification_status='conditions_not_independently_checked',
                    warnings=['仅分别求导。仍需确认附近可微、分母导数非零及导数比值极限的适用条件。'])
    f = parse(q['expression'],functions=q.get('functions'))
    if f.has(s.zoo,s.nan): raise MathInputError('表达式包含未定义值。')
    if tool == 'math.series':
        p = point_value(q['point'],finite=True)
        at_point = s.simplify(f).subs(x, p)
        if at_point.has(s.zoo,s.nan,s.oo,-s.oo) or at_point.is_finite is not True:
            raise MathInputError('当前表达式在展开点非解析或无法确认；请改用极限工具。')
        expansion = s.series(f, x, p, q['through_degree'] + 1)
        poly, rem = expansion.removeO(), expansion.getO()
        t = s.Dummy('t', real=True)
        try: s.Poly(s.expand(poly.subs(x,t+p)),t)
        except s.PolynomialError: raise MathInputError('含分数幂、负幂或非解析项；不作为普通泰勒多项式返回。')
        # Reject nonsmooth expansions for which right-side series would mislead.
        if f.has(s.Abs) or f.has(s.oo,-s.oo): raise MathInputError('当前普通泰勒工具不支持绝对值或无穷常量。')
        return pack(expansion, input_latex=s.latex(f),polynomial=str(poly), remainder=str(rem) if rem is not None else None,
                    remainder_latex=s.latex(rem) if rem is not None else None,
                    relation='asymptotic_expansion', verification_status='not_independently_checked',
                    sufficient_nonzero_term=poly != 0,
                    warnings=['保留实际余项；截断式不是原式恒等式。'] + (['当前阶数未出现非零项，不能据此判定抵消后的主导项。'] if poly == 0 else []))
    if tool == 'math.limit':
        p = point_value(q['point'])
        values = sides(f,x,p,q['direction'])
        if any(v.has(s.Limit) for v in values): raise MathInputError('符号引擎未能求出极限。')
        if len(values) == 2 and values[0] != values[1]:
            return {'status':'does_not_exist','left':str(values[0]),'right':str(values[1]),
                    'result_latex':r'\text{双侧极限不存在}', 'verification_status':'not_independently_checked'}
        v = values[0]
        return pack(v, input_latex=s.latex(f),status='unresolved' if v.has(s.nan,s.zoo) else ('unbounded' if v in (s.oo,-s.oo) else 'ok'),
                    direction=q['direction'], verification_status='not_independently_checked')
    if tool == 'math.transform':
        action = q['action']
        if action == 'substitute':
            v = parse(q['value'],functions=q.get('functions')); result = f.subs(x,v)
        else: result = {'simplify':s.simplify,'expand':s.expand,'factor':s.factor,'cancel':s.cancel}[action](f)
        return pack(result, input_latex=s.latex(f),relation='substitution' if action == 'substitute' else 'identity_on_original_domain',
                    verification_status='not_independently_checked',
                    warnings=['保留原式定义域；消去因子不意味着原式在被消去的零点有定义。'])
    if tool == 'math.verify_step':
        g = parse(q['proposed'],functions=q.get('functions'))
        if q['relation'] == 'identity':
            return check_identity(f,g)
        if s.simplify(g) == 0: raise MathInputError('等价无穷小比较式不能为零。')
        p = point_value(q['point'])
        fv, gv = sides(f,x,p,'both'), sides(g,x,p,'both')
        ratios = sides(f/g,x,p,'both')
        equivalent = all(v == 0 for v in fv+gv) and all(v == 1 for v in ratios)
        return {'verdict':'equivalent_infinitesimals' if equivalent else 'not_equivalent_or_unresolved',
                'relation':'asymptotic', 'verification_status':'symbolic_check',
                'warnings':['等价只表示比值趋于 1；不能自动在抵消差式中替换。']}
    raise MathInputError('不支持的操作。')
