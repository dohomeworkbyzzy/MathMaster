import {Formula} from './math';

export function ToolVerification({result}:{result:Record<string,unknown>}){
 const verdict=String(result.verdict||'');
 if(!verdict)return null;
 const labels:Record<string,string>={symbolically_equal_on_common_domain:'核验通过',not_equal:'核验不通过',undetermined:'暂时无法确认',equivalent_infinitesimals:'等价无穷小核验通过',not_equivalent_or_unresolved:'未确认等价无穷小'};
 const witness=result.counterexample as {functions:Record<string,string>;values:Record<string,string>;left:string;right:string}|null;
 return <div className="ai-verification" role="status"><b>{labels[verdict]||'核验结果待确认'}</b>{!!result.proposed_latex&&<><p>你提交的式子：</p><Formula latex={String(result.proposed_latex)}/></>}{result.operation==='check_derivative'&&<p>上方公式是按原函数计算的参考导数。</p>}{witness&&<p>反例：{Object.entries(witness.functions).map(([key,value])=>key+' = '+value).join('；')}，取 {Object.entries(witness.values).map(([key,value])=>key+' = '+value).join('，')}，参考值为 {witness.left}，提交值为 {witness.right}。</p>}{Array.isArray(result.warnings)&&result.warnings.map((warning,i)=><p key={i}>{String(warning)}</p>)}</div>;
}
