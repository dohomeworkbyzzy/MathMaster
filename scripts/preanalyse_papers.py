"""Resumeable local knowledge build: reuse cited 408 analyses; analyse scanned maths once."""
import argparse
import concurrent.futures
from functools import lru_cache
import hashlib
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import db,grading
from backend.ai import knowledge as k
from backend.ai import provider

SKILLS=[('cache','408.cache.address_unit'),('Cache','408.cache.address_unit'),('TLB','408.cache.address_unit'),('页置换','408.os.replacement'),('页面置换','408.os.replacement'),('最短路径','408.ds.graph'),('生成树','408.ds.graph'),('子网','408.network.prefix')]

@lru_cache(maxsize=64)
def source_html(path):
    from lxml import html
    return html.parse(path)

def local_408(q,source_dir):
    from lxml import html
    year=q['spec'].get('year');n=int(q['number']);solution=q['reference_answer'];tags=[];topic='408 基础概念与条件分析';warnings=[]
    bok=source_dir/f'{year}.html'
    if bok.exists():
        t=source_html(str(bok));cards=t.xpath(f'//article[@id="{year}-{n:02}"]')
        if cards:
            labels=cards[0].xpath('.//span[@class="question-kicker"]');topic=labels[0].text_content() if labels else topic
    # Supplement explanations only when the choice letters agree with the bank key.
    cs=ROOT/'artifacts/grading-acceptance'/f'408-{year}.html'
    supplemental=False
    if cs.exists():
        t=source_html(str(cs));h=t.xpath(f'//h5[@id="{n}"]')
        if h:
            node=h[0].getnext()
            while node is not None and node.tag not in ('h3','h4','h5'):
                choice=node.get('data-answer')
                if choice and choice==q['spec']['answer_key']:
                    detail=node.xpath('.//div[contains(@class,"explanation")]')
                    if detail:
                        solution+='\n\n补充参考解析（公开整理，待核对）：\n'+detail[0].text_content().strip();supplemental=True
                        tags=[s.strip() for s in (node.get('data-tags') or '').split(',') if s.strip()]
                node=node.getnext()
    if tags:topic+=' · '+','.join(tags[:3])
    skills=[skill for pattern,skill in SKILLS if pattern in q['text']]
    skills=list(dict.fromkeys(skills))[:6]
    method='按定义与题设条件分析';first='题目考察哪个概念？先说出你打算依据的定义或条件。'
    if any(x in q['text'] for x in ['页置换','页面置换','FIFO','LRU']):method='按访问顺序模拟';first='先确认置换规则和初始页框状态，你准备怎样处理第一次访问？'
    elif any(x in q['text'] for x in ['Cache','cache']):method='统一单位并划分地址字段';first='先确认按字节还是按字寻址，块大小使用什么单位？'
    elif '最短路径' in q['text']:method='逐步模拟路径选择';first='先检查边权和路径的定义，再说明你会怎样比较候选路径。'
    elif '子网' in q['text']:method='按地址前缀分析';first='先确认网络地址和掩码，再说明你怎样区分网络位与主机位。'
    payload={'question_id':q['id'],'question_text':q['text'],'uncertain':False,'has_diagram':bool(q['images']),
             'topic':topic,'problem':{'kind':'scratch','skill_ids':skills},
             'methods':[{'name':method,'first_question':first,'checkpoints':['核对题设条件','选择适用定义或规则','说明判断依据']}],
             'private_solution':solution[:9000],'rubric':'按题干标注的小题分值逐项核对结论、必要过程和条件。允许不同的合理解法；未提供官方细则时只给建议分。',
             'warnings':warnings,'solution_basis':'reference','reference_source':f'https://zhenti.beokayy.club/paper/{year}'}
    source='408 题库与公开参考解析'+('（含选项核对后的补充解析）' if supplemental else '')
    k.put(q,payload,source)
    return supplemental

def math_reference(q):
    match=re.fullmatch(r'real-(math[12])-(\d{4})-q(\d+)',q['id'])
    if not match:return None
    subject,year,num=match.groups();path=db.DATA/'sources/math'/f'{subject}-{year}.html'
    if not path.exists():return None
    tree=source_html(str(path));head=tree.xpath(f'//h5[@id="{int(num)}"]')
    if not head:return None
    node=head[0].getnext();solutions=[];tags=[]
    while node is not None and node.tag not in ('h3','h4','h5'):
        classes=node.get('class') or ''
        if 'choice-container' in classes:
            if node.get('data-answer')!=q['spec']['answer_key']:return None
            solutions.extend(node.xpath('.//div[contains(@class,"explanation")]'))
            tags=[x.strip() for x in (node.get('data-tags') or '').split(',') if x.strip()]
        elif 'solution-detail' in classes:solutions.append(node)
        node=node.getnext()
    solution='\n\n'.join(x.text_content().strip() for x in solutions)
    return {'solution':solution,'tags':tags,'url':f'https://www.csgraduates.com/study_methods/math/{subject}/{year}/'} if solution else None

def enrich(q,value):
    ref=math_reference(q)
    if ref:
        value['private_solution']=ref['solution'][:9000];value['solution_basis']='reference';value['reference_source']=ref['url']
        value['rubric']='按当前题库参考答案与题干分值评阅，核对关键条件和实际作答过程。公开解析不是官方细则；网页转录公式需以原题图为准。'
    else:
        # An unverified model proof is never promoted to the grading reference.
        value['private_solution']='';value['solution_basis']='model_draft'
    return value

def update(rid,total,completed,failed,metrics,status='running'):
    with db.connection() as c:c.execute('UPDATE knowledge_runs SET status=?,completed=?,failed=?,details=?,updated_at=? WHERE id=?',(status,completed,failed,k.dump(metrics),k.now(),rid))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--subject',default='');parser.add_argument('--limit',type=int,default=0);parser.add_argument('--workers',type=int,default=3);parser.add_argument('--batch-size',type=int,default=3);parser.add_argument('--pilot',action='store_true');args=parser.parse_args()
    db.init_db();grading.init(recover_interrupted=False);k.init()
    with db.connection() as c:
        clause=' WHERE subject=?' if args.subject else ''
        ids=c.execute('SELECT id FROM questions'+clause+' ORDER BY subject,paper_id,CAST(number AS INTEGER)',(args.subject,) if args.subject else ()).fetchall()
        questions=[k.bank_question(c,r['id']) for r in ids]
    if args.limit:questions=questions[:args.limit]
    total=len(questions);rid=uuid.uuid4().hex;completed=failed=0;metrics={'source_reused':0,'already_stored':0,'model_calls':0,'response_cache_hits':0,'prompt_tokens':0,'completion_tokens':0,'needs_review':0,'current_subject':args.subject or '全部'}
    with db.connection() as c:c.execute('INSERT INTO knowledge_runs VALUES(?,?,?,?,?,?,?,?)',(rid,'running',total,0,0,k.dump(metrics),k.now(),k.now()))
    todo=[]
    for q in questions:
        existing=k.get(q)
        if existing:
            if q['subject']=='408':
                local_408(q,db.DATA/'sources/408')
            else:
                payload={key:value for key,value in existing.items() if key in k.Analysis.model_fields};k.put(q,enrich(q,payload),'原题参考解析 + 模型题图预解析（待核对）',existing.get('model_id',''))
            metrics['already_stored']+=1;completed+=1;continue
        if q['subject']=='408' and q['id'].startswith('real-408-'):
            try:local_408(q,db.DATA/'sources/408');metrics['source_reused']+=1;completed+=1
            except Exception:k.error(q,'公开解析读取失败，等待重新处理');failed+=1
        else:
            ref=math_reference(q)
            if ref:q['_reference_solution']=ref['solution'][:6500]
            todo.append(q)
        if completed and (completed+failed)%40==0:update(rid,total,completed,failed,metrics);print(f'已整理 {completed}/{total}，失败 {failed}',flush=True)
    # Keep supplemental sources in the same backed-up source directory.
    supplemental=db.DATA/'sources/408/analysis-sources';supplemental.mkdir(parents=True,exist_ok=True)
    for path in (ROOT/'artifacts/grading-acceptance').glob('408-*.html'):
        shutil.copyfile(path,supplemental/path.name)
    update(rid,total,completed,failed,metrics)
    if todo:
        profile=provider.load_profile()
        if not 1<=args.batch_size<=4 or not 1<=args.workers<=4:raise ValueError('batch-size/workers 必须为1至4')
        batches=[todo[i:i+args.batch_size] for i in range(0,len(todo),args.batch_size)]
        def task(batch):
            last=None
            for attempt in range(2):
                try:return batch,*k.analyse(batch,profile)
                except (ValueError,OSError) as exc:
                    last=str(exc)
                    # No infinite retries, and no paid retries after a broken credential/configuration.
                    if any(s in last for s in ['401','403','密钥','配置','不支持']):break
                    if attempt==0:time.sleep(2)
            return batch,None,{'error':last or '预解析失败'}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures=[pool.submit(task,b) for b in batches]
                for future in concurrent.futures.as_completed(futures):
                    batch,values,result=future.result()
                    if values:
                        for q in batch:
                            try:
                                k.put(q,enrich(q,values[q['id']]),'原题参考解析 + 模型题图预解析（待核对）',profile.model_id);completed+=1;metrics['needs_review']+=int(values[q['id']]['uncertain'])
                            except ValueError:k.error(q,'题目在预解析时已修改，等待重新处理');failed+=1
                        usage=result.get('usage',{});metrics['model_calls']+=int(not result.get('cache_hit'));metrics['response_cache_hits']+=int(bool(result.get('cache_hit')))
                        metrics['prompt_tokens']+=usage.get('prompt_tokens',0);metrics['completion_tokens']+=usage.get('completion_tokens',0)
                    else:
                        for q in batch:k.error(q,result['error']);failed+=1
                    update(rid,total,completed,failed,metrics);print(f'已解析 {completed}/{total}，失败 {failed}，模型批次 {metrics["model_calls"]}，待核对 {metrics["needs_review"]}',flush=True)
        except BaseException:
            update(rid,total,completed,failed,metrics,'interrupted');raise
    status='complete' if failed==0 else 'partial'
    update(rid,total,completed,failed,metrics,status)
    result={'id':rid,'status':status,'total':total,'completed':completed,'failed':failed,'metrics':metrics}
    artifact=ROOT/'artifacts/preanalysis';artifact.mkdir(parents=True,exist_ok=True);(artifact/(rid+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
    if failed:sys.exit(1)

if __name__=='__main__':main()
