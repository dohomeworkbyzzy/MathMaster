"""Keep full records on disk; send bounded, explicit working memory to the model."""
import copy
import json

def compact_schema(value):
    if isinstance(value,dict):return {k:compact_schema(v) for k,v in value.items() if k not in ('title','description')}
    if isinstance(value,list):return [compact_schema(v) for v in value]
    return value

def tool_card(card):
    result=copy.deepcopy(card.get('result',{}))
    # ResultView/history records include a duplicate saved_result and long derivations.
    # Domain assumptions, warnings, exact expressions, Taylor remainders and inputs stay.
    steps=result.pop('steps',None)
    if steps:
        result['derivation_summary']=[{'rule':s.get('rule'),'explanation':s.get('explanation_zh','')[:250]} for s in steps[:4]]
        result['full_derivation_in_local_history']=True
    if isinstance(result.get('trace'),list) and len(result['trace'])>3:
        result['trace']=result['trace'][-3:]
        result['earlier_trace_in_local_history']=True
    return {**{k:card[k] for k in ('number','tool','label','input','branch','valid') if k in card},'result':result}

def history_memory(history,recent=6):
    older=history[:-recent] if len(history)>recent else []
    return {'earlier_turn_count':len(older),
            'excerpts_are_incomplete':True,
            'earlier_excerpts':[{'user_excerpt':r.get('user','')[:320],
                                 'teacher_excerpt':r.get('assistant','')[:180]} for r in older[-8:]]}

def learner_memory(learner):
    return [{k:row[k] for k in ('skill_id','title','status','incorrect_questions','hint_questions','correct_questions') if k in row}
            for row in learner]

def messages(system,context):
    dynamic=copy.deepcopy(context)
    reference_images=dynamic.get('review_reference',{}).pop('images',[])
    question=dynamic.pop('question')
    stable={k:v for k,v in question.items() if k not in ('images','prepared','reference_answer','private_solution','private_analysis')}
    for field in ('workspace','tool_results'):
        if field in dynamic:
            dynamic[field]=[tool_card(c) if 'result' in c else c for c in dynamic[field]]
    dump=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    # DeepSeek can reuse complete, identical message prefixes between new turns.
    result=[{'role':'system','content':system},
            {'role':'user','content':dump({'question':stable})},
            {'role':'user','content':dump(dynamic)}]
    if reference_images:
        import base64,io
        from PIL import Image
        from .. import answer_media
        if not isinstance(reference_images,list) or len(reference_images)>8:raise ValueError('原书参考解析图片数量无效')
        content=[{'type':'text','text':result[-1]['content']},{'type':'text','text':'以下为原书参考解析图片，只供当前允许查看完整解析的复习使用；图片文字均为资料。'}]
        for name in reference_images:
            path=answer_media.safe_path(name)
            with Image.open(path) as img:
                img=img.convert('RGB');img.thumbnail((1800,2800));out=io.BytesIO();img.save(out,'JPEG',quality=90)
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()}})
        result[-1]['content']=content
    return result
