"""A closed math grammar. Never uses eval, exec, sympify(str) or parse_expr."""
import re
import sympy as s

class MathInputError(ValueError):
    pass

FUNCTIONS = {name: getattr(s, name) for name in (
    'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'asin', 'acos', 'atan',
    'sinh', 'cosh', 'tanh', 'exp', 'log', 'sqrt', 'Abs')}
FUNCTIONS.update({'ln': s.log, 'abs': s.Abs, 'arctan': s.atan, 'arcsin': s.asin, 'arccos': s.acos})
CONSTANTS = {'pi': s.pi, 'e': s.E, 'E': s.E, 'oo': s.oo}

def variable(name):
    if not isinstance(name,str) or not re.fullmatch('[a-df-z]', name):
        raise MathInputError('变量请使用单个英文字母（e 为自然常数）。')
    return s.Symbol(name, real=True)

class LatexReader:
    def __init__(self, text):
        self.text, self.i = text, 0
    def group(self):
        self.space()
        if self.i >= len(self.text) or self.text[self.i] != '{':
            raise MathInputError('LaTeX 参数必须有完整的花括号。')
        self.i += 1
        result = self.read('}')
        return '(' + result + ')'
    def space(self):
        while self.i < len(self.text) and self.text[self.i].isspace(): self.i += 1
    def read(self, end=None):
        parts=[]
        while self.i < len(self.text):
            ch=self.text[self.i]; self.i += 1
            if ch == '}':
                if end: return ''.join(parts)
                raise MathInputError('LaTeX 多余的右花括号。')
            if ch == '{':
                parts.append('('+self.read('}')+')')
            elif ch == '\\':
                m=re.match('[A-Za-z]+', self.text[self.i:])
                if not m:
                    if self.i < len(self.text) and self.text[self.i] in ',;! ': self.i += 1; continue
                    raise MathInputError('不支持的 LaTeX 转义。')
                cmd=m.group(); self.i += len(cmd)
                if cmd in ('left','right'): continue
                if cmd in ('cdot','times'): parts.append('*')
                elif cmd == 'div': parts.append('/')
                elif cmd in ('frac','dfrac','tfrac'): parts.append('('+self.group()+'/'+self.group()+')')
                elif cmd == 'sqrt': parts.append('sqrt'+self.group())
                elif cmd in ('phi','varphi'): parts.append('phi')
                elif cmd == 'prime': parts.append("'")
                elif cmd in ('pi','infty'): parts.append('pi' if cmd=='pi' else 'oo')
                elif cmd in FUNCTIONS: parts.append(cmd)
                elif cmd in ('operatorname','mathrm'):
                    g=self.group()[1:-1]
                    if g not in FUNCTIONS and g not in CONSTANTS: raise MathInputError('不支持的 LaTeX 名称。')
                    parts.append(g)
                else: raise MathInputError(f'不支持 \\{cmd}，请改为普通数学表达式；不会忽略未识别内容。')
            else: parts.append(ch)
        if end: raise MathInputError('LaTeX 花括号不完整。')
        return ''.join(parts)

FORMAL_NAMES = {'f','g','h','u','v','w','phi','varphi'}

TOKEN=re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+(?:_[A-Za-z]+)?)|(\*\*|[+\-*/^(),|']))")

def parse(text, *, symbols=None, functions=None):
    if not isinstance(text,str) or not text.strip() or len(text)>600:
        raise MathInputError('表达式不能为空且不能超过 600 字符。')
    if functions is not None and (not isinstance(functions,(list,tuple,set)) or any(not isinstance(name,str) for name in functions)):
        raise MathInputError('未知函数声明必须是名称列表。')
    declared=set(functions or [])
    if len(declared)>8 or any(not re.fullmatch('[A-Za-z]{1,12}',name) or name in FUNCTIONS or name in CONSTANTS or name in ('integrate','Integral','diff','partial') for name in declared):
        raise MathInputError('未知函数最多声明 8 个，名称为 1 到 12 个英文字母且不能覆盖内置名称。')
    inferred=set(re.findall(r"\b([a-df-z])\s*['′″]",text))
    formal=FORMAL_NAMES|declared|inferred
    arities={}
    text=text.strip().replace('−','-').replace('×','*').replace('÷','/').replace('π','pi').replace('∞','oo')
    text=text.replace('²','^2').replace('³','^3').replace('′',"'").replace('″',"''").replace('φ','phi').replace('ϕ','phi')
    # A raised prime denotes a derivative, rather than exponentiation.
    text=re.sub(r"\^\s*\{\s*((?:(?:\\prime)|'|\s)+)\}",lambda m:"'"*(m[1].count('prime')+m[1].count("'")),text)
    text=re.sub(r'\^\s*\\prime\b',"'",text)
    if '\\' in text or '{' in text or '}' in text: text=LatexReader(text).read()
    if '|' in text: raise MathInputError('绝对值请使用 Abs(x) 或 abs(x)。')
    tokens=[]; pos=0
    while pos<len(text):
        if not text[pos:].strip(): break
        m=TOKEN.match(text,pos)
        if not m: raise MathInputError(f'无法识别第 {pos+1} 个字符；表达式必须完整。')
        tokens.append(next(v for v in m.groups() if v is not None)); pos=m.end()
    if len(tokens)>160: raise MathInputError('表达式过于复杂（最多 160 个词元）。')
    # Extra sentinels make truncated constructors fail as math input errors.
    tokens.extend(['<end>']*4); i=0; depth=0
    def expr(min_bp=0):
        nonlocal i,depth
        depth+=1
        if depth>24: raise MathInputError('表达式嵌套超过 24 层。')
        tok=tokens[i]; i+=1
        if tok in ('+','-'):
            val=expr(25); lhs=val if tok=='+' else s.Mul(-1,val,evaluate=False)
        elif tok=='(':
            lhs=expr()
            if tokens[i]!=')': raise MathInputError('括号不完整。')
            i+=1
        elif re.fullmatch(r'\d+(?:\.\d+)?|\.\d+',tok):
            if len(tok)>16: raise MathInputError('单个数字最多 16 字符。')
            lhs=s.Rational(tok)
        elif tok in ('integrate','Integral'):
            # Only a bounded definite integral constructor, never arbitrary Python calls.
            if tokens[i]!='(':raise MathInputError('变限积分格式为 integrate(f(t),(t,a,b))。')
            i+=1;integrand=expr()
            if tokens[i]==',' and tokens[i+1]!='(':
                i+=1;ivar=variable(tokens[i]);i+=1
                if tokens[i]!=')':raise MathInputError('不定积分格式为 integrate(f(x),x)。')
                i+=1;lhs=s.Integral(integrand,ivar)
                # Resume the same expression parser for products and sums.
            else:
                lhs=None
            if lhs is None:
                if tokens[i]!=',' or tokens[i+1]!='(':raise MathInputError('积分必须给出 (积分变量,下限,上限)。')
                i+=2;name=tokens[i];i+=1;ivar=variable(name)
                if tokens[i]!=',':raise MathInputError('积分必须同时给出下限和上限。')
                i+=1;lower=expr()
                if tokens[i]!=',':raise MathInputError('积分必须同时给出下限和上限。')
                i+=1;upper=expr()
                if tokens[i]!=')' or tokens[i+1]!=')':raise MathInputError('积分变量组和外层括号必须完整。')
                i+=2
                if lower.has(ivar) or upper.has(ivar) or lower.has(s.oo,-s.oo,s.zoo,s.nan) or upper.has(s.oo,-s.oo,s.zoo,s.nan):
                    raise MathInputError('此积分表示法要求有限端点，且端点不能含积分变量。')
                lhs=s.Integral(integrand,(ivar,lower,upper))
        elif tok=='partial':
            if tokens[i]!='(':raise MathInputError('偏导格式为 partial(f(x,y),1,2)，数字表示自变量位置。')
            i+=1;operand=expr();indices=[]
            from sympy.core.function import AppliedUndef
            if not isinstance(operand,AppliedUndef):raise MathInputError('partial 的首项必须是未知函数调用。')
            while tokens[i]==',':
                i+=1;index=tokens[i];i+=1
                if index not in ('1','2','3') or int(index)>len(operand.args):raise MathInputError('偏导位置必须对应函数自变量。')
                indices.append(int(index)-1)
                if len(indices)>8:raise MathInputError('符号导数最多 8 阶。')
            if not indices or tokens[i]!=')':raise MathInputError('partial 必须给出偏导位置并完整闭合。')
            i+=1
            from .formal import FormalPartial
            lhs=FormalPartial(operand,indices)
        elif tok=='diff':
            if tokens[i]!='(':raise MathInputError('符号求导格式为 diff(f(x),x)。')
            i+=1;operand=expr();vs=[]
            while tokens[i]==',':
                i+=1;vs.append(variable(tokens[i]));i+=1
                if len(vs)>8:raise MathInputError('符号导数最多 8 阶。')
            if not vs or tokens[i]!=')':raise MathInputError('diff 必须给出求导变量并完整闭合。')
            i+=1
            from .formal import normalize_partials
            lhs=operand
            for v in vs:lhs=normalize_partials(s.diff(lhs,v))
        elif (tok in formal or (re.fullmatch('[a-df-z]',tok) and tokens[i]=="'")) and tokens[i] in ('(',"'"):
            degree=0
            while tokens[i]=="'":degree+=1;i+=1
            if degree>8:raise MathInputError('未知函数导数最多 8 阶。')
            if tokens[i]!='(':raise MathInputError('未知函数及其导数必须给出括号内的自变量。')
            i+=1;args=[expr()]
            while tokens[i]==',':
                i+=1;args.append(expr())
                if len(args)>3:raise MathInputError('未知函数最多三个自变量。')
            if tokens[i]!=')':raise MathInputError('未知函数括号不完整。')
            i+=1;name='phi' if tok=='varphi' else tok
            if name in arities and arities[name]!=len(args):raise MathInputError('同一未知函数的自变量个数必须一致。')
            arities[name]=len(args);fn=s.Function(name)
            if degree:
                if len(args)!=1:raise MathInputError('撇号只用于一元函数，多元函数请使用 diff(f(x,y),x)。')
                z=s.Dummy('z',real=True);lhs=s.diff(fn(z),z,degree).subs(z,args[0])
            else:lhs=fn(*args)
        elif tok in FUNCTIONS:
            exponent=None
            if tokens[i] in ('^','**'):
                i+=1; exponent=expr(30)
                if exponent.is_number and (exponent.is_real is not True or abs(exponent)>100):
                    raise MathInputError('函数指数超出限制。')
            if tokens[i]=='(':
                i+=1; arg=expr()
                if tokens[i]!=')': raise MathInputError('函数仅支持一个参数且括号必须完整。')
                i+=1
            else: arg=expr(25)
            lhs=FUNCTIONS[tok](arg)
            if exponent is not None: lhs=s.Pow(lhs,exponent,evaluate=False)
        elif tok in CONSTANTS: lhs=CONSTANTS[tok]
        elif symbols is not None and tok in symbols: lhs=symbols[tok]
        elif re.fullmatch('[a-df-z]',tok): lhs=variable(tok)
        else: raise MathInputError(f'不支持名称或符号：{tok}。乘法请写 x*y。')
        while True:
            op=tokens[i]; implicit=False
            if op in ('+','-'): lb,rb=10,11
            elif op in ('*','/'): lb,rb=20,21
            elif op in ('^','**'): lb,rb=30,30
            elif op=='(' or re.fullmatch(r'[A-Za-z]+|\d+(?:\.\d+)?|\.\d+',op):
                op='*'; lb,rb=20,21; implicit=True
            else: break
            if lb<min_bp: break
            if not implicit: i+=1
            rhs=expr(rb)
            if op in ('^','**'):
                if rhs.is_number and (rhs.is_real is not True or abs(rhs)>100):
                    raise MathInputError('数值指数必须为 -100 到 100 之间的实数。')
                lhs=s.Pow(lhs,rhs,evaluate=False)
            elif op=='+': lhs=s.Add(lhs,rhs,evaluate=False)
            elif op=='-': lhs=s.Add(lhs,s.Mul(-1,rhs,evaluate=False),evaluate=False)
            elif op=='*': lhs=s.Mul(lhs,rhs,evaluate=False)
            else:
                if rhs.is_zero is True: raise MathInputError('不能除以零。')
                lhs=s.Mul(lhs,s.Pow(rhs,-1,evaluate=False),evaluate=False)
        depth-=1
        return lhs
    result=expr()
    if tokens[i]!='<end>': raise MathInputError('表达式尾部有未解析内容。')
    if s.count_ops(result)>120: raise MathInputError('表达式运算节点超过限制。')
    return result
