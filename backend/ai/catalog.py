PRIVATE={'reference_answer','private_solution','private_analysis'}
DEFAULT_SKILLS={
 'math2.limit.indeterminate':('未定式识别',[]),
 'math2.limit.cancellation':('差式抵消',['math2.limit.indeterminate']),
 'math2.limit.expansion_order':('展开阶数',['math2.limit.cancellation']),
 'math2.limit.leading_term':('渐近主导项',['math2.limit.expansion_order']),
 'math2.limit.lhopital_conditions':('洛必达条件',['math2.limit.indeterminate']),
 'math2.limit.logarithm':('幂指型极限取对数',['math2.limit.indeterminate']),
 'math2.algebra.product_sign':('乘积与符号',[]),
 'math2.derivative.chain':('链式法则',[]),
 'math2.matrix.row_conditions':('行变换条件',[]),
 '408.cache.address_unit':('寻址单位',[]),
 '408.cache.offset':('块内偏移',['408.cache.address_unit']),
 '408.cache.index':('组数与组索引',['408.cache.offset']),
 '408.cache.tag':('标记字段',['408.cache.index']),
 '408.os.replacement':('页面置换规则',[]),
 '408.ds.graph':('图算法规则',[]),
 '408.network.prefix':('子网前缀',[])}

def public(q):
 result={k:v for k,v in q.items() if k not in PRIVATE}
 if 'document_parts' in result:result['document_parts']=[p for p in result['document_parts'] if p.get('role')!='answer']
 return result
