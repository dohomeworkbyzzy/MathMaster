"""Translate the visible reasoning setting into the selected provider's parameters."""
import re

LABELS={'default':'默认','none':'关闭','enabled':'开启思考','low':'低','medium':'中','high':'高','xhigh':'超高','max':'最高'}
BUDGET={'low':1024,'medium':4096,'high':8192,'xhigh':12288,'max':16384}

def family(p):
    model=p.model_id.lower().split('/')[-1]
    if p.protocol not in ('openai_chat_completions','anthropic_messages'):return 'embedding'
    if p.protocol=='openai_chat_completions':
        if model.startswith(('gpt-6.1-sol','gpt-6-astra')):return 'gpt6_reasoning'
        if model.startswith(('gpt-6-sol','gpt-6-luna')):return 'gpt6_optional'
    if model.startswith('deepseek'):return 'deepseek'
    if model.startswith('glm-5.3'):return 'glm53'
    if model.startswith('glm-5.2'):return 'glm52'
    if model.startswith('glm-'):return 'glm'
    if model.startswith('qwen3') and 'coder' not in model:return 'qwen'
    if p.protocol=='anthropic_messages':
        if re.search(r'claude-(?:opus|sonnet|haiku)-(?:4[-.][6-9]|[5-9])',model):return 'claude_adaptive'
        return 'claude_budget'
    return 'compatible'

def options(p):
    kind=family(p)
    if kind=='embedding':values=['default']
    elif kind=='gpt6_reasoning':values=['default','low','medium','high','xhigh','max']
    elif kind=='gpt6_optional':values=['default','none','low','medium','high','xhigh','max']
    elif kind=='glm53':values=['default','low','high','max']
    elif kind=='glm52':values=['default','none','high','max']
    elif kind=='glm':values=['default','none','enabled']
    elif kind=='deepseek':values=['default','none','low','high','max']
    elif kind=='qwen':values=['default','none','low','medium','high','max']
    else:values=['default','none','low','medium','high']
    if kind=='claude_adaptive' and 'opus' in p.model_id.lower():values.append('max')
    return [{'value':value,'label':LABELS[value]} for value in values]

def describe(p):
    hint='强度越高，通常等待更久、消耗更多 tokens；默认沿用原高级参数或供应商默认值。'
    if family(p)=='glm53':hint+=' GLM-5.3 仅支持低、高、最高，不能关闭思考。'
    elif family(p)=='compatible':hint+=' 兼容接口需支持 reasoning_effort 参数。'
    return {'reasoning_effort':p.reasoning_effort,'reasoning_options':options(p),'reasoning_hint':hint}

def apply(p,payload):
    effort=p.reasoning_effort
    if effort not in {o['value'] for o in options(p)}:raise ValueError('当前模型不支持这个思考强度，请选择可用档位。')
    kind=family(p)
    output_key='max_tokens'
    if kind in ('gpt6_reasoning','gpt6_optional'):
        output_key='max_completion_tokens'
        payload[output_key]=payload.get(output_key,payload.get('max_tokens',2048));payload.pop('max_tokens',None)
        effective=payload.get('reasoning_effort') if effort=='default' else effort
        if effective!='none':
            for key in ('temperature','top_p','top_logprobs','logprobs'):payload.pop(key,None)
    if effort=='default':return payload
    for key in ('thinking','reasoning_effort','enable_thinking','thinking_budget'):payload.pop(key,None)
    raw=payload.get('output_config') or {}
    if not isinstance(raw,dict):raise ValueError('高级 output_config 必须为 JSON 对象。')
    config=dict(raw);config.pop('effort',None)
    if config:payload['output_config']=config
    else:payload.pop('output_config',None)
    if p.protocol=='anthropic_messages':
        if effort=='none':payload['thinking']={'type':'disabled'}
        elif kind=='deepseek':payload.update(thinking={'type':'enabled'},output_config={**config,'effort':effort})
        elif kind in ('glm53','glm52','glm'):
            payload['thinking']={'type':'enabled'}
            if effort!='enabled':payload['reasoning_effort']=effort
        elif kind=='claude_adaptive':payload.update(thinking={'type':'adaptive'},output_config={**config,'effort':effort})
        else:payload['thinking']={'type':'enabled','budget_tokens':BUDGET[effort]}
        if effort!='none':payload.pop('temperature',None)
    elif kind in ('deepseek','glm53','glm52','glm'):
        payload['thinking']={'type':'disabled' if effort=='none' else 'enabled'}
        if effort not in ('none','enabled'):payload['reasoning_effort']=effort
    elif kind=='qwen':
        payload['enable_thinking']=effort!='none'
        if effort!='none':payload['thinking_budget']=BUDGET[effort]
    else:payload['reasoning_effort']=effort
    if effort not in ('none','default'):
        # Reserve output space for both reasoning and the structured teaching reply.
        if not any(key in p.extra_body for key in ('max_tokens','max_completion_tokens')):payload[output_key]=BUDGET.get(effort,4096)+2048
        budget=payload.get('thinking',{}).get('budget_tokens',0)
        if budget and (not isinstance(payload['max_tokens'],int) or budget>=payload['max_tokens']):raise ValueError('高级 max_tokens 必须大于思考预算，请增大输出上限或降低强度。')
    return payload
