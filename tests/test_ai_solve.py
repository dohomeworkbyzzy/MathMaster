import pytest
import sympy as s
from backend.ai.registry import compute
from backend.parser import parse,MathInputError

@pytest.mark.parametrize('zx,zy',[('zx','zy'),('z_x','z_y')])
def test_2026_math2_implicit_derivative_equations_with_named_unknowns_and_parameters(zx,zy):
    result=compute('math.solve',{'equations':[f'1-a*{zx}=exp(y+a*z)*a*{zx}',f'-a*{zy}=exp(y+a*z)*(1+a*{zy})'],
                                'variables':[zx,zy],'parameters':['a','y','z']})
    a,y,z=s.symbols('a y z',real=True);E=s.exp(y+a*z)
    assert len(result['solutions'])==1
    first,second=(parse(result['solutions'][0][name]) for name in (zx,zy))
    assert s.simplify(first-1/(a*(1+E)))==0
    assert s.simplify(second+E/(a*(1+E)))==0
    assert s.simplify(first-second-1/a)==0
    assert s.simplify(1-a*first-E*a*first)==0
    assert s.simplify(-a*second-E*(1+a*second))==0
    assert 'a != 0' in result['assumptions'] and result['solutions_latex']
    assert result['verification_status']=='substitution_checked'

def test_named_symbols_remain_closed_and_parameters_must_be_explicit():
    with pytest.raises(MathInputError):parse('zx+1')
    with pytest.raises(MathInputError):parse('z_x+1')
    with pytest.raises(ValueError):compute('math.solve',{'equations':['__import__(x)=0'],'variables':['__import__']})
    with pytest.raises(MathInputError):compute('math.solve',{'equations':['a*zx=1'],'variables':['zx']})
    with pytest.raises(ValueError):compute('math.solve',{'equations':['pi=1'],'variables':['pi']})
