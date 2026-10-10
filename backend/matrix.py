"""Own exact elementary-row-operation engine; SymPy is only the cross-check."""
import sympy as s
from .parser import parse, MathInputError
from .engine import Trace, response, equal, all_verified


def read_matrix(value):
    if not isinstance(value,list) or not 1<=len(value)<=8: raise MathInputError('矩阵行数必须为 1 到 8。')
    width=len(value[0]) if isinstance(value[0],list) else 0
    if not 1<=width<=8 or any(not isinstance(row,list) or len(row)!=width for row in value):
        raise MathInputError('矩阵需为规则表格，列数为 1 到 8。')
    vals=[s.simplify(parse(str(v))) for row in value for v in row]
    if any(v.has(s.zoo,s.nan,s.oo,-s.oo) for v in vals): raise MathInputError('矩阵元素必须为有限表达式。')
    return s.Matrix(len(value),width,vals)

def serial(m): return [[str(v) for v in row] for row in m.tolist()]

def mequal(a,b): return a.shape==b.shape and all(equal(x,y) for x,y in zip(a,b))

class RowEngine:
    def __init__(self,m,tr,columns=None):
        self.m=m.copy(); self.tr=tr; self.steps=[]; self.assumptions=[]
        self.columns=m.cols if columns is None else columns; self.swaps=0
    def apply(self,kind,row,other=None,factor=None):
        before=self.m.copy(); after=before.copy(); n=row+1
        if kind=='swap':
            after.row_swap(row,other); self.swaps+=1
            label=f'R{n} ↔ R{other+1}'; meaning='交换两行，选择非零主元；方程组解集保持不变。'; effect='行列式乘以 -1'; mult=s.S.NegativeOne
            reconstructed=before.copy(); reconstructed.row_swap(row,other)
        elif kind=='scale':
            after.row_op(row,lambda v,j:s.simplify(factor*v))
            label=f'R{n} ← ({factor}) R{n}'; meaning='用非零系数乘整行，将主元归一；保持方程组解集。'; effect=f'行列式乘以 {factor}'; mult=factor
            reconstructed=before.copy(); reconstructed.row_op(row,lambda v,j:s.simplify(factor*v))
        else:
            after.row_op(row,lambda v,j:s.simplify(v+factor*before[other,j]))
            label=f'R{n} ← R{n} + ({factor}) R{other+1}'; meaning='将另一行的倍数加到本行，以消去主元列元素；保持行空间和方程组解集。'; effect='行列式不变'; mult=s.S.One
            reconstructed=before.copy(); reconstructed.row_op(row,lambda v,j:s.simplify(v+factor*before[other,j]))
        ok=mequal(after,reconstructed)
        det_check=None
        if before.rows==before.cols:
            det_check=equal(after.det(),mult*before.det()); ok=ok and det_check
        st=self.tr.step(kind,before,after,label+'。'+meaning,kind='elementary_row',verified=ok,
            operation_type=kind,target_row=n,source_row=other+1 if other is not None else None,
            coefficient=str(factor) if factor is not None else None,before_matrix=serial(before),after_matrix=serial(after),
            mathematical_meaning=meaning,determinant_effect=effect,determinant_multiplier=str(mult),determinant_verified=det_check)
        if self.columns<before.cols:
            st['augmentation_column']=self.columns
            def augmented_latex(m):
                spec='c'*self.columns+'|'+'c'*(m.cols-self.columns)
                body=r'\\'.join(' & '.join(s.latex(v) for v in row) for row in m.tolist())
                return r'\left[\begin{array}{'+spec+'}'+body+r'\end{array}\right]'
            st['before_latex']=augmented_latex(before);st['after_latex']=augmented_latex(after)
        self.steps.append(st); self.m=after
    def reduce(self,reduced=True):
        row=0; pivots=[]
        for col in range(self.columns):
            if row>=self.m.rows: break
            candidates=[i for i in range(row,self.m.rows) if self.m[i,col].is_zero is False]
            if not candidates: candidates=[i for i in range(row,self.m.rows) if self.m[i,col].is_zero is not True]
            if not candidates: continue
            p=candidates[0]
            if self.m[p,col].is_zero is None:
                condition=s.latex(self.m[p,col])+r'\ne 0'
                self.assumptions.append(condition)
                self.tr.warnings.append('含符号主元：行变换结论仅在列出的非零条件下成立；特殊参数值请代入后重新计算。')
            if p!=row: self.apply('swap',row,p)
            pivot=self.m[row,col]
            if reduced and pivot!=1: self.apply('scale',row,factor=s.simplify(1/pivot))
            targets=range(self.m.rows) if reduced else range(row+1,self.m.rows)
            for i in targets:
                if i==row or self.m[i,col].is_zero is True: continue
                factor=s.simplify(-self.m[i,col]/self.m[row,col])
                self.apply('replace',i,row,factor)
            pivots.append(col); row+=1
        return self.m,pivots


def cofactor(m,tr):
    if m.rows==1: return m[0,0],[]
    terms=[]; kids=[]
    for j in range(m.cols):
        minor=m.minor_submatrix(0,j); val,child=cofactor(minor,tr)
        term=(-1)**j*m[0,j]*val; terms.append(term)
        kids.append(tr.step('cofactor_term',(-1)**j*m[0,j]*minor.det(),term,
            f'第一行第 {j+1} 列：系数乘对应代数余子式。',child,verified=equal(term,(-1)**j*m[0,j]*minor.det())))
    result=s.simplify(sum(terms))
    st=tr.step('cofactor_expansion',s.Determinant(m),result,'沿第一行展开，递归计算余子式。',kids,
        kind='determinant',verified=equal(m.det(),result),formula_latex=r'\det A=\sum_{j=1}^{n}(-1)^{1+j}a_{1j}M_{1j}')
    return result,[st]


def matrix_job(req):
    tr=Trace(); a=read_matrix(req['matrix']); op=req.get('action','rref'); steps=[]; assumptions=['矩阵元素采用精确有理数或实符号。']
    result=None; checked=False; status='ok'; method='精确矩阵运算'
    if op in ('add','subtract','multiply'):
        b=read_matrix(req.get('matrix_b'))
        if op in ('add','subtract') and a.shape!=b.shape: raise MathInputError('加减法要求矩阵形状相同。')
        if op=='multiply' and a.cols!=b.rows: raise MathInputError('乘法要求 A 的列数等于 B 的行数。')
        if op=='add': result=s.Matrix(a.rows,a.cols,lambda i,j:s.simplify(a[i,j]+b[i,j])); ref=a+b
        elif op=='subtract': result=s.Matrix(a.rows,a.cols,lambda i,j:s.simplify(a[i,j]-b[i,j])); ref=a-b
        else: result=s.Matrix(a.rows,b.cols,lambda i,j:s.simplify(sum(a[i,k]*b[k,j] for k in range(a.cols)))); ref=a*b
        checked=mequal(result,ref)
        steps=[tr.step(op,a,result,'逐元素加减；乘法则对每个输出元素计算对应行与列的内积。',kind='matrix_operation',verified=checked,
            formula_latex=r'c_{ij}=\sum_k a_{ik}b_{kj}' if op=='multiply' else r'c_{ij}=a_{ij}\pm b_{ij}',matrix_b=serial(b))]
    elif op=='transpose':
        result=s.Matrix(a.cols,a.rows,lambda i,j:a[j,i]); checked=mequal(result,a.T)
        steps=[tr.step(op,a,result,'将第 i 行第 j 列元素移动到第 j 行第 i 列。',kind='transpose',verified=checked)]
    elif op in ('determinant','inverse') and a.rows!=a.cols: raise MathInputError('行列式与逆矩阵要求方阵。')
    elif op=='determinant':
        if req.get('method')=='cofactor':
            if a.rows>5: raise MathInputError('按行展开仅限 5 阶以内；更大矩阵请用初等变换法。')
            result,steps=cofactor(a,tr); method='按行展开法'
        else:
            eng=RowEngine(a,tr); upper,pivots=eng.reduce(False)
            result=s.simplify((-1)**eng.swaps*s.prod(upper[i,i] for i in range(a.rows)))
            steps=eng.steps; assumptions+=eng.assumptions; method='初等变换法 · 上三角主对角线乘积'
            st=tr.step('triangular_determinant',s.Determinant(a),result,'将上三角矩阵对角元素相乘，并补回行交换的符号。',kind='determinant',verified=equal(result,a.det()),upper_matrix=serial(upper),swaps=eng.swaps)
            steps.append(st)
        checked=equal(result,a.det())
    elif op in ('rref','rank','inverse','solve'):
        method='可追踪初等行变换 + SymPy 交叉验证'
        if op=='inverse':
            det=s.simplify(a.det())
            if det.is_zero is True:
                result=None; status='singular'; checked=True
                tr.warnings.append('行列式为 0，矩阵奇异，不存在逆矩阵。')
                steps=[tr.step('singular',s.Determinant(a),s.S.Zero,'先检查行列式；为零时不能进行求逆。',kind='determinant',verified=equal(a.det(),0))]
            else:
                if det.is_zero is None: assumptions.append(s.latex(det)+r'\ne0')
                eng=RowEngine(a.row_join(s.eye(a.rows)),tr,a.cols); reduced,pivots=eng.reduce()
                result=reduced[:,a.cols:]; steps=eng.steps; assumptions+=eng.assumptions
                checked=mequal(reduced[:,:a.cols],s.eye(a.rows)) and mequal(a*result,s.eye(a.rows)) and mequal(result,a.inv())
                steps.append(tr.step('inverse_verification',a*result,s.eye(a.rows),'独立验证 A·A⁻¹=I，并与 SymPy 的逆矩阵比较。',verified=checked,kind='matrix_identity'))
        elif op=='solve':
            b=read_matrix(req.get('matrix_b'))
            if b.rows!=a.rows or b.cols!=1: raise MathInputError('线性方程组右端 B 必须为与 A 行数相同的列向量。')
            eng=RowEngine(a.row_join(b),tr,a.cols); reduced,pivots=eng.reduce(); steps=eng.steps; assumptions+=eng.assumptions
            inconsistent=False
            for i in range(reduced.rows):
                if all(reduced[i,j].is_zero is True for j in range(a.cols)):
                    rhs=reduced[i,a.cols]
                    if rhs.is_zero is False: inconsistent=True
                    elif rhs.is_zero is None:
                        assumptions.append(s.latex(rhs)+'=0'); tr.warnings.append('该参数方程组仅在零系数行的右端也为零时相容。')
            if inconsistent:
                status='no_solution'; checked=s.linsolve((a,b))==s.EmptySet
                tr.warnings.append('出现 0=非零数 的矛盾行，方程组无解。')
            else:
                free=[j for j in range(a.cols) if j not in pivots]; params={j:s.Symbol(f't{k}',real=True) for k,j in enumerate(free)}
                sol=[params.get(j,s.S.Zero) for j in range(a.cols)]
                for i,p in enumerate(pivots): sol[p]=s.simplify(reduced[i,a.cols]-sum(reduced[i,j]*sol[j] for j in free))
                result=s.Matrix(sol); checked=mequal(a*result,b)
                if free: status='infinite_solutions'; tr.warnings.append('有自由变量，t0、t1 等为任意实数。')
                steps.append(tr.step('solution_verification',a*result,b,'回代原方程组 A·x=b 验证。',kind='matrix_identity',verified=checked))
        else:
            eng=RowEngine(a,tr); reduced,pivots=eng.reduce(); steps=eng.steps; assumptions+=eng.assumptions
            if op=='rank':
                result=s.Integer(len(pivots)); checked=result==a.rank()
                steps.append(tr.step('rank_count',reduced,result,'行最简形中非零行的个数即为秩。',kind='rank',verified=checked,nonzero_rows=len(pivots)))
            else: result=reduced; checked=mequal(result,a.rref()[0])
        if any('ne' in c for c in assumptions): status='conditional' if status=='ok' else status
    else: raise MathInputError('不支持的矩阵运算。')
    out=response('matrix',a,result,method,tr,checked and all_verified(steps),assumptions,action=op,status=status)
    out['steps']=steps
    if isinstance(result,s.MatrixBase): out['result_matrix']=serial(result)
    if status=='singular': out['result_latex']=r'\text{奇异矩阵，不存在逆矩阵}'
    if status=='no_solution': out['result_latex']=r'\text{方程组无解}'
    return out
