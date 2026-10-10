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
    if not re.fullmatch('[a-df-z]', name):
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

TOKEN=re.compile(r'\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+)|(\*\*|[+\-*/^(),|]))')

def parse(text):
    if not isinstance(text,str) or not text.strip() or len(text)>600:
        raise MathInputError('表达式不能为空且不能超过 600 字符。')
    text=text.strip().replace('−','-').replace('×','*').replace('÷','/').replace('π','pi').replace('∞','oo')
    text=text.replace('²','^2').replace('³','^3')
    if '\\' in text or '{' in text or '}' in text: text=LatexReader(text).read()
    if '|' in text: raise MathInputError('绝对值请使用 Abs(x) 或 abs(x)。')
    tokens=[]; pos=0
    while pos<len(text):
        if not text[pos:].strip(): break
        m=TOKEN.match(text,pos)
        if not m: raise MathInputError(f'无法识别第 {pos+1} 个字符；表达式必须完整。')
        tokens.append(next(v for v in m.groups() if v is not None)); pos=m.end()
    if len(tokens)>160: raise MathInputError('表达式过于复杂（最多 160 个词元）。')
    tokens.append('<end>'); i=0; depth=0
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
