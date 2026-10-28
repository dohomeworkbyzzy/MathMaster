import sympy as s
from ..parser import parse,variable,MathInputError

def compute(q):
 x=variable(q['variable']);params=[variable(p) for p in q['parameters']]
 left,right=parse(q['left']),parse(q['right'])
 diff=s.series(left-right,x,0,q['through_degree']+1).removeO().expand()
 equations=[diff.coeff(x,k) for k in range(q['through_degree']+1)]
 solutions=s.solve(equations,params,dict=True)
 return {'solutions':[{str(k):str(v) for k,v in solution.items()} for solution in solutions],
         'relation':'coefficient_matching_through_requested_degree','verification_status':'symbolic_check',
         'warnings':['只匹配用户请求的次数；不能自动推断更高阶项或一般等价关系。']}
