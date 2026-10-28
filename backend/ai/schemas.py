"""Closed per-tool input contracts. Validation also runs inside the worker."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Expr = Annotated[str, Field(min_length=1, max_length=600)]
Var = Annotated[str, Field(pattern=r'^[a-df-z]$')]
class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Expression(Input):
    expression: Expr
    variable: Var = 'x'
class Series(Expression):
    point: Expr = '0'
    through_degree: Annotated[int, Field(strict=True, ge=0, le=12)] = 2
class Limit(Expression):
    point: Expr = '0'
    direction: Literal['both', 'left', 'right'] = 'both'
class FormalExpression(Expression):
    functions:list[Annotated[str,Field(pattern=r'^[A-Za-z]{1,12}$')]]=Field(default_factory=list,max_length=8)

class Differentiate(FormalExpression):
    variables:list[Var]|None=Field(default=None,min_length=1,max_length=8)
    order: Annotated[int, Field(strict=True, ge=1, le=8)] = 1
class CheckDerivative(Differentiate):
    proposed:Expr

class Integrate(Expression):
    lower: Expr | None = None
    upper: Expr | None = None
    @model_validator(mode='after')
    def paired(self):
        if (self.lower is None) != (self.upper is None):
            raise ValueError('定积分需要同时指定上下限')
        return self
class Transform(FormalExpression):
    action: Literal['simplify', 'expand', 'factor', 'cancel', 'substitute'] = 'simplify'
    value: Expr | None = None
    @model_validator(mode='after')
    def value_required(self):
        if self.action == 'substitute' and self.value is None:
            raise ValueError('代入操作需要 value')
        return self
class Verify(FormalExpression):
    proposed: Expr
    relation: Literal['identity', 'asymptotic'] = 'identity'
    point: Expr = '0'
class LHopital(Input):
    numerator: Expr
    denominator: Expr
    variable: Var = 'x'
    point: Expr = '0'
    direction: Literal['both', 'left', 'right'] = 'both'
    condition_note: Annotated[str, Field(min_length=1, max_length=1000)]
Cell = Annotated[str, Field(min_length=1, max_length=80)]
Row = Annotated[list[Cell], Field(min_length=1, max_length=8)]
Grid = Annotated[list[Row], Field(min_length=1, max_length=8)]
class Matrix(Input):
    matrix: Grid
    action: Literal['rref', 'rank', 'determinant', 'inverse', 'solve', 'add', 'subtract', 'multiply', 'transpose'] = 'rref'
    matrix_b: Grid | None = None
    method: Literal['row', 'cofactor'] = 'row'
class Cache(Input):
    address_bits: Annotated[int, Field(strict=True, ge=1, le=64)]
    addressing_unit: Literal['byte', 'word']
    word_bytes: Annotated[int, Field(strict=True, ge=1, le=16)] | None = None
    data_capacity: Annotated[int, Field(strict=True, ge=1, le=2**40)]
    capacity_unit: Literal['B', 'KiB', 'MiB']
    block_size: Annotated[int, Field(strict=True, ge=1, le=2**30)]
    block_unit: Literal['B', 'KiB']
    ways: Annotated[int, Field(strict=True, ge=1, le=65536)]
    stage: Literal['offset', 'index', 'tag', 'all']
    address: Annotated[int, Field(strict=True, ge=0)] | None = None
    @model_validator(mode='after')
    def word_required(self):
        if self.addressing_unit == 'word' and self.word_bytes is None:
            raise ValueError('字寻址需明确每字字节数')
        return self
SCHEMAS = {'math.series': Series, 'math.limit': Limit, 'math.differentiate': Differentiate,
           'math.integrate': Integrate, 'math.check_derivative': CheckDerivative, 'math.transform': Transform, 'math.verify_step': Verify,
           'math.lhopital_step': LHopital, 'math.matrix': Matrix, 'cs.cache_address': Cache}

class SeriesMatch(Input):
    left: Expr
    right: Expr
    parameters: list[Var] = Field(min_length=1,max_length=4)
    variable: Var = 'x'
    through_degree: int = Field(ge=1,le=8)
SCHEMAS['math.series_match']=SeriesMatch

SolveVar = Annotated[str, Field(pattern=r'^[a-df-z](?:_?[a-df-z])?$')]
class Solve(Input):
    equations: list[Expr] = Field(min_length=1,max_length=6)
    variables: list[SolveVar] = Field(min_length=1,max_length=4)
    parameters: list[Var] = Field(default_factory=list,max_length=6)
    @model_validator(mode='after')
    def distinct_symbols(self):
        names=self.variables+self.parameters
        if len(set(names))!=len(names) or any(v in ('pi','oo','ln') for v in names):
            raise ValueError('未知量与参数不能重复，不能使用保留常量或函数名')
        return self
SCHEMAS['math.solve']=Solve

class PageReplacement(Input):
    pages: list[Annotated[int,Field(strict=True,ge=0,le=1000000)]] = Field(min_length=1,max_length=256)
    frames: int = Field(ge=1,le=16)
    algorithm: Literal['FIFO','LRU']
    step: int = Field(default=0,ge=0,le=256)
    steps: int = Field(default=1,ge=1,le=256)
    run_remaining: bool = False
class Edge(Input):
    u: str = Field(min_length=1,max_length=20)
    v: str = Field(min_length=1,max_length=20)
    weight: float = Field(default=1,ge=0,le=1000000,allow_inf_nan=False)
class Graph(Input):
    nodes: list[Annotated[str,Field(min_length=1,max_length=20)]] = Field(min_length=1,max_length=32)
    edges: list[Edge] = Field(max_length=128)
    source: str = Field(min_length=1,max_length=20)
    directed: bool = True
    algorithm: Literal['bfs','dfs','dijkstra']
    step: int = Field(default=0,ge=0,le=32)
    steps: int = Field(default=1,ge=1,le=32)
    run_remaining: bool = False
class Subnet(Input):
    cidr: str = Field(min_length=3,max_length=30)
    host_convention: Literal['traditional','point_to_point']
    part: Literal['mask','network','hosts','all']
SCHEMAS.update({'cs.page_replacement':PageReplacement,'cs.graph':Graph,'cs.subnet':Subnet})
