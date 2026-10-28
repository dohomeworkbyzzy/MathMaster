"""Round-trippable output and finite witnesses for closed symbolic expressions."""
import sympy as s
from sympy.core.function import AppliedUndef
from sympy.printing.str import StrPrinter


class FormalPrinter(StrPrinter):
    def _partial(self, derivative, replacements=None):
        f=derivative.expr
        if not isinstance(f,AppliedUndef):return None
        # Positions distinguish f_1(x,x) from f_2(x,x). Substitute the
        # evaluation points only after identifying the differentiation slots.
        if any(f.args.count(v)!=1 for v in derivative.variables):return None
        indices=[f.args.index(v)+1 for v in derivative.variables]
        args=[arg.xreplace(replacements or {}) for arg in f.args]
        call=f.func.__name__+'('+','.join(self._print(arg) for arg in args)+')'
        return 'partial('+call+','+','.join(map(str,indices))+')'

    def _print_FormalPartial(self,value):
        function,indices=value.args
        return 'partial('+self._print(function)+','+','.join(str(int(k)+1) for k in indices)+')'

    def _print_Subs(self, value):
        derivative=value.expr
        if isinstance(derivative,s.Derivative) and len(value.variables)==1 and len(value.point)==1:
            f=derivative.expr;z=value.variables[0]
            if isinstance(f,AppliedUndef) and f.args==(z,) and all(v==z for v in derivative.variables):
                return f.func.__name__+"'"*len(derivative.variables)+'('+self._print(value.point[0])+')'
        if isinstance(derivative,s.Derivative):
            result=self._partial(derivative,dict(zip(value.variables,value.point)))
            if result:return result
        return super()._print_Subs(value)

    def _print_Derivative(self,value):
        f=value.expr
        if isinstance(f,AppliedUndef) and len(f.args)==1 and all(v==f.args[0] for v in value.variables):
            return f.func.__name__+"'"*len(value.variables)+'('+self._print(f.args[0])+')'
        result=self._partial(value)
        if result:return result
        return 'diff('+self._print(f)+','+','.join(self._print(v) for v in value.variables)+')'

    def _print_Integral(self,value):
        result=self._print(value.function)
        for limit in value.limits:
            spec=self._print(limit[0]) if len(limit)==1 else '('+','.join(self._print(v) for v in limit)+')'
            result='integrate('+result+','+spec+')'
        return result


def text(value):return FormalPrinter().doprint(value)


class FormalPartial(s.Expr):
    """Positional formal partial; chain rules keep repeated arguments distinct."""
    is_commutative=True
    def __new__(cls, function, indices):
        indices=s.Tuple(*sorted(int(k) for k in indices))
        if isinstance(function,AppliedUndef) and len(function.args)==1:
            z=s.Dummy('z',real=True)
            return s.diff(function.func(z),z,len(indices)).subs(z,function.args[0])
        return s.Expr.__new__(cls,function,indices)

    def _eval_derivative(self, variable):
        function,indices=self.args
        return s.Add(*(FormalPartial(function,(*indices,k))*s.diff(arg,variable)
                       for k,arg in enumerate(function.args)))

    def _latex(self, printer):
        function,indices=self.args
        positions=','.join(str(int(k)+1) for k in indices)
        return printer._print(function.func.__name__)+r'_{'+positions+'}'+r'\left('+','.join(printer._print(arg) for arg in function.args)+r'\right)'


def normalize_partials(value):
    """Remove CAS substitution placeholders before another chain rule."""
    if isinstance(value,FormalPartial):return value
    derivative=value.expr if isinstance(value,s.Subs) else value
    if isinstance(derivative,s.Derivative) and isinstance(derivative.expr,AppliedUndef):
        f=derivative.expr
        if len(f.args)>1 and all(f.args.count(v)==1 for v in derivative.variables):
            replacements=dict(zip(value.variables,value.point)) if isinstance(value,s.Subs) else {}
            args=[arg.xreplace(replacements) for arg in f.args]
            return FormalPartial(f.func(*args),[f.args.index(v) for v in derivative.variables])
    if not value.args:return value
    return value.func(*(normalize_partials(arg) for arg in value.args))


def counterexample(left,right):
    """One finite legal witness refutes an unrestricted identity, never proves one."""
    # Restrict witnesses to polynomial constructions, with no unverified poles,
    # roots or logarithm domains at the sample points.
    for expression in (left,right):
        for node in s.preorder_traversal(expression):
            if node.is_Function and not isinstance(node,AppliedUndef):return None
            if isinstance(node,s.Pow) and (node.exp.is_integer is not True or node.exp.is_nonnegative is not True):return None
    functions=sorted({f.func for e in (left,right) for f in e.atoms(AppliedUndef)},key=str)
    if not functions or len(functions)>8 or any(len(f.args)!=1 for e in (left,right) for f in e.atoms(AppliedUndef)):return None
    names=sorted(left.free_symbols|right.free_symbols,key=str)
    for degree in (2,3,4):
        a,b=left,right;definitions={}
        for index,fn in enumerate(functions):
            a=a.replace(fn,lambda arg:arg**degree+index*arg)
            b=b.replace(fn,lambda arg:arg**degree+index*arg)
            definitions[str(fn)+'(t)']='t**'+str(degree)+(('+'+str(index)+'*t') if index else '')
        for shift in (1,2):
            point={v:s.Integer(i+shift) for i,v in enumerate(names)}
            av=a.subs(point).doit();bv=b.subs(point).doit();residual=s.simplify(av-bv)
            if av.is_finite is True and bv.is_finite is True and av.is_real is True and bv.is_real is True and residual.is_zero is False:
                return {'functions':definitions,'values':{str(v):str(n) for v,n in point.items()},'left':text(av),'right':text(bv),
                        'note':'该光滑多项式函数与取值给出反例；仅用于未附加其他函数约束的恒等式核验。'}
    return None
