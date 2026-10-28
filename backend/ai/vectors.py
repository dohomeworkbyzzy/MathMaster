"""Knowledge-first neural retrieval. No answers or learner text enter document embeddings."""
import hashlib
import json
import math
import os
import re
import struct
import threading
import uuid
from pathlib import Path
import httpx
from .. import db
from . import knowledge as k,profiles,provider,cache
from .catalog import DEFAULT_SKILLS

VERSION='knowledge-vector-v2'
_encoder=None
_encoder_path=None
_encoder_lock=threading.Lock()
_stop=threading.Event()
_wake=threading.Event()
_worker=None

def folder():return Path(os.environ.get('MATHMASTER_EMBEDDING_MODEL_DIR',str(db.DATA/'models/bge-small-zh-v1.5')))

def ready(profile):
    if profile.protocol!='local_bge':return bool(profile.api_key)
    return all((folder()/f).is_file() for f in ('tokenizer.json','model_quantized.onnx','manifest.json'))

def space(profile):
    identity={'version':VERSION,'protocol':profile.protocol,'base_url':profile.base_url.rstrip('/'),'model':profile.model_id,'options':profile.extra_body}
    if profile.protocol=='local_bge':
        identity['weights']=hashlib.sha256((folder()/'manifest.json').read_bytes()).hexdigest() if (folder()/'manifest.json').is_file() else 'unavailable'
        identity['pooling']='cls-l2-query-prefix-256'
    else:identity['credential']=cache.key(profile.api_key)
    return cache.key(identity)

def normalize(values):
    if not isinstance(values,(list,tuple)) or not 1<=len(values)<=16384:raise provider.ProviderError('向量接口返回的维度无效。')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):raise provider.ProviderError('向量接口返回非有效数值。')
    norm=math.sqrt(sum(x*x for x in values))
    if norm<1e-12:raise provider.ProviderError('向量接口返回空向量。')
    return [x/norm for x in values]

def _local(texts,query=False):
    global _encoder,_encoder_path
    try:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:raise provider.ProviderError('内置向量依赖未安装，请安装 requirements.txt 中的依赖。') from None
    if not ready(profiles.as_profile(profiles.LOCAL)):raise provider.ProviderError('内置中文向量模型尚未准备好。')
    # Tokenizer padding/truncation configuration and session initialization are shared.
    with _encoder_lock:
        location=str(folder().resolve())
        if _encoder is None or _encoder_path!=location:
            manifest=json.loads((folder()/'manifest.json').read_text(encoding='utf-8'))
            for filename in ('model_quantized.onnx','tokenizer.json'):
                with (folder()/filename).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                if digest!=manifest['files'][filename]['sha256']:raise provider.ProviderError('内置向量模型文件校验失败，请重新下载模型。')
            options=ort.SessionOptions();options.intra_op_num_threads=min(4,os.cpu_count() or 1);options.inter_op_num_threads=1
            session=ort.InferenceSession(str(folder()/'model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
            tokenizer=Tokenizer.from_file(str(folder()/'tokenizer.json'));tokenizer.enable_truncation(max_length=256);tokenizer.enable_padding(pad_id=0,pad_token='[PAD]')
            _encoder=(session,tokenizer);_encoder_path=location
        session,tokenizer=_encoder
        tokens=tokenizer.encode_batch([('为这个句子生成表示以用于检索相关文章：' if query else '')+t for t in texts])
        inputs={'input_ids':np.array([t.ids for t in tokens],dtype=np.int64),
                'attention_mask':np.array([t.attention_mask for t in tokens],dtype=np.int64),
                'token_type_ids':np.array([t.type_ids for t in tokens],dtype=np.int64)}
        outputs=session.run(None,{i.name:inputs[i.name] for i in session.get_inputs()})[0]
        vectors=outputs[:,0,:] if outputs.ndim==3 else outputs
    return [normalize(v.tolist()) for v in vectors]

def embed(texts,profile=None,query=False,cancelled=None):
    profile=profile or profiles.selected('embedding')
    if not texts:return []
    if cancelled and cancelled():raise provider.ProviderError('向量任务已暂停。')
    if profile.protocol=='local_bge':return _local(texts,query)
    if profile.protocol!='openai_embeddings':raise provider.ProviderError('向量 API 需要 OpenAI embeddings 协议。')
    identity=cache.key({'space':space(profile),'role':'query' if query else 'document','texts':texts})
    with cache.single_flight('embedding',identity,cancelled,provider.ProviderError):
        existing=cache.get('embedding',identity)
        if existing is not None:return [normalize(v) for v in existing['vectors']]
        generation=cache.generation()
        payload={**profile.extra_body,'model':profile.model_id,'input':texts,'encoding_format':'float'}
        try:
            # Use the same cancellable transport as the tutor, without serializing secrets.
            import asyncio
            async def send():
                async with httpx.AsyncClient(timeout=profile.timeout) as client:
                    task=asyncio.create_task(client.post(provider.endpoint(profile,'embeddings'),headers=provider.headers(profile),json=payload))
                    try:
                        while not task.done():
                            if cancelled and cancelled():task.cancel();raise provider.ProviderError('向量任务已暂停。')
                            await asyncio.sleep(.1)
                        return await task
                    finally:
                        if not task.done():task.cancel()
            response=asyncio.run(send())
        except httpx.RequestError:raise provider.ProviderError('向量 API 网络请求失败，请检查连接。') from None
        if response.status_code!=200:raise provider.ProviderError(f'向量 API 调用失败（HTTP {response.status_code}），请检查配置与额度。')
        try:
            body=response.json();rows=sorted(body['data'],key=lambda r:r['index'])
            if [r['index'] for r in rows]!=list(range(len(texts))):raise ValueError()
            vectors=[normalize(r['embedding']) for r in rows]
            if len({len(v) for v in vectors})!=1:raise ValueError()
        except (KeyError,ValueError,TypeError):raise provider.ProviderError('向量 API 返回格式不完整。') from None
        cache.record_remote('embedding',body.get('usage',{}))
        cache.put('embedding',identity,{'vectors':vectors},30*86400,generation)
        return vectors

def clean(text):
    # Strip formula spans, numerical parameters and answer-like equations; retain concept words.
    text=re.sub(r'\$[^$]*\$|\\\([^)]*\\\)|\\\[[\s\S]*?\\\]',' ',str(text))
    text=re.sub(r'\b\d+(?:\.\d+)?\b',' ',text)
    return re.sub(r'\s+',' ',text).strip()[:800]

# A small public syllabus vocabulary supplements broad historical labels. Only concept names
# are added, never numerical parameters, a complete stem, options, or reference answers.
CONCEPTS=[
 ('高速缓存 Cache',r'cache|高速缓存|高速缓冲|组相联|直接映射|全相联'),
 ('地址划分：标记位、组索引、块内偏移',r'块内|组索引|标记位|标记字段|组号|组相联|直接映射'),
 ('缓存映射方式',r'组相联|全相联|直接映射|cache映射'),
 ('缓存命中率与访问时间',r'命中率|命中时间|缺失率'),
 ('页式虚拟存储与地址转换',r'虚拟地址|页表|页式|页号|页内|tlb'),
 ('页面置换算法',r'页面置换|页置换|缺页|页框'),
 ('进程互斥与同步、信号量',r'互斥|同步|信号量|临界区|临界资源|pv操作'),
 ('进程调度',r'进程调度|调度算法|时间片|周转时间'),
 ('文件系统与磁盘',r'文件系统|inode|文件目录|磁盘调度'),
 ('最短路径算法',r'最短路径|dijkstra|floyd'),
 ('最小生成树',r'最小生成树|kruskal|prim'),
 ('图的遍历与拓扑排序',r'拓扑排序|深度优先|广度优先|dfs|bfs'),
 ('二叉树与树的遍历',r'二叉树|先序|中序|后序|树的遍历'),
 ('查找与散列表',r'散列|哈希|折半查找|二叉排序树'),
 ('排序算法',r'排序算法|快速排序|堆排序|归并排序|插入排序|冒泡排序'),
 ('网络地址、子网与前缀',r'子网|网络前缀|子网掩码|cidr|ipv4'),
 ('TCP 可靠传输与拥塞控制',r'tcp|拥塞控制|慢开始|拥塞窗口|重传'),
 ('泰勒展开与展开阶数',r'泰勒|taylor|展开阶数|麦克劳林'),
 ('等价无穷小与阶的比较',r'等价无穷小|无穷小|主导项'),
 ('洛必达法则及使用条件',r'洛必达'),
 ('曲线的渐近线',r'渐近线'),
 ('定积分与变限积分',r'定积分|变限积分'),
 ('不定积分与积分方法',r'不定积分|分部积分|换元积分'),
 ('矩阵秩与线性方程组',r'矩阵的秩|矩阵秩|线性方程组'),
 ('特征值、特征向量与对角化',r'特征值|特征向量|对角化'),
]

def syllabus(text):
    return [label for label,pattern in CONCEPTS if re.search(pattern,text,re.I)]

def document(q,analysis):
    topic=clean(analysis['topic'])
    skill_ids=analysis['problem'].get('skill_ids',[])
    skills=[DEFAULT_SKILLS[s][0] for s in skill_ids if s in DEFAULT_SKILLS]
    methods=[clean(m['name']) for m in analysis['methods'] if not re.search(r'[=<>]',m['name'])]
    checkpoints=[clean(x) for m in analysis['methods'] for x in m['checkpoints'] if not re.search(r'[=<>]',x)]
    concepts=list(dict.fromkeys([x for x in re.split(r'[·、，,;；/]',topic) if x.strip()]+skills))
    concepts=[x.strip() for x in concepts if x.strip()]
    context=topic+' '+' '.join(methods)+' '+' '.join(checkpoints)
    # Broad 408 labels often omit the actual tested concept. Use the transcribed stem only
    # when it has a substantive cue, so an incidental Cache option in a RAID question is ignored.
    if q['subject']=='408':
        stem=re.split(r'\n\s*[A-D][.．、:]|\n\s*[（(][A-D][）)]',analysis['question_text'])[0]
        context+=' '+stem
    concepts=list(dict.fromkeys(concepts+syllabus(context)))
    text='考察方向：'+topic+'。核心知识：'+('、'.join(concepts))+'。解题方法：'+'、'.join(methods)+'。理解要点：'+'；'.join(checkpoints)
    return {'text':text,'topic':topic,'concepts':concepts,'skills':skill_ids}

def init():
    with db.connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS question_embeddings(
         question_id TEXT NOT NULL REFERENCES questions(id),space TEXT NOT NULL,fingerprint TEXT NOT NULL,
         document_hash TEXT NOT NULL,dimensions INTEGER NOT NULL,vector BLOB NOT NULL,
         topic TEXT NOT NULL,concepts TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL,
         PRIMARY KEY(question_id,space));
        CREATE TABLE IF NOT EXISTS embedding_jobs(
         id TEXT PRIMARY KEY,paper_id TEXT,question_ids TEXT NOT NULL,status TEXT NOT NULL,
         phase TEXT NOT NULL,total INTEGER NOT NULL,completed INTEGER NOT NULL DEFAULT 0,
         failed INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        ''')

def all_questions(paper_id=None,ids=None):
    with db.connection() as c:
        if ids is None:ids=[r[0] for r in c.execute('SELECT id FROM questions'+(' WHERE paper_id=?' if paper_id else ''),(paper_id,) if paper_id else ())]
        return [k.bank_question(c,qid) for qid in ids if c.execute('SELECT 1 FROM questions WHERE id=?',(qid,)).fetchone()]

def index_questions(qs,profile=None,cancelled=None,progress=None):
    profile=profile or profiles.selected('embedding');active=space(profile);pending=[];completed=0
    with db.connection() as c:
        for q in qs:
            analysis=k.get(q)
            if not analysis:continue
            doc=document(q,analysis);fp=k.fingerprint(q);dh=cache.key(doc['text'])
            row=c.execute('SELECT fingerprint,document_hash FROM question_embeddings WHERE question_id=? AND space=?',(q['id'],active)).fetchone()
            if row and row['fingerprint']==fp and row['document_hash']==dh:completed+=1;continue
            pending.append((q,fp,dh,doc))
    if progress:progress(completed)
    for begin in range(0,len(pending),16):
        batch=pending[begin:begin+16];values=embed([b[3]['text'] for b in batch],profile,cancelled=cancelled)
        with db.connection() as c:
            old=c.execute('SELECT dimensions FROM question_embeddings WHERE space=? LIMIT 1',(active,)).fetchone()
            if old and old[0]!=len(values[0]):raise provider.ProviderError('该模型返回的向量维度发生变化，请新建独立配置。')
            for (q,fp,dh,doc),value in zip(batch,values):
                current=k.bank_question(c,q['id'])
                if k.fingerprint(current)!=fp:continue
                c.execute('INSERT OR REPLACE INTO question_embeddings VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (q['id'],active,fp,dh,len(value),struct.pack('<'+'f'*len(value),*value),doc['topic'],k.dump(doc['concepts']),doc['text'],k.now()))
                completed+=1
        if progress:progress(completed)
    return {'completed':completed,'space':active,'dimensions':len(values[0]) if pending else None}

def search(text='',qid=None,subject='',limit=8,extra_skills=None):
    profile=profiles.selected('embedding');active=space(profile);source=None
    if qid:
        with db.connection() as c:q=k.bank_question(c,qid)
        analysis=k.get(q)
        if not analysis:return {'items':[],'reason':'当前题目尚未完成知识点解析。','space':active}
        source=document(q,analysis);text=source['text'];subject=q['subject']
        if extra_skills:text+='。待巩固：'+'、'.join(DEFAULT_SKILLS[s][0] for s in extra_skills if s in DEFAULT_SKILLS)
    if not text.strip():raise ValueError('请描述要查找的知识点。')
    with db.connection() as c:
        rows=c.execute('''SELECT e.*,q.subject,q.number,q.paper_id,p.title AS paper_title,q.text FROM question_embeddings e
          JOIN questions q ON e.question_id=q.id LEFT JOIN papers p ON p.id=q.paper_id
          WHERE e.space=? AND (?='' OR q.subject=?) AND (? IS NULL OR q.id<>?)''',(active,subject,subject,qid,qid)).fetchall()
        live={r['question_id']:k.bank_question(c,r['question_id']) for r in rows}
    rows=[r for r in rows if r['fingerprint']==k.fingerprint(live[r['question_id']])]
    if not rows:return {'items':[],'reason':'当前向量模型尚无有效索引，请在 API 配置中建立索引。','space':active}
    vector=embed([text],profile,query=True)[0];results=[]
    query_concepts=set(source['concepts'] if source else syllabus(text))
    for row in rows:
        if row['dimensions']!=len(vector):continue
        stored=struct.unpack('<'+'f'*row['dimensions'],row['vector'])
        cosine=sum(a*b for a,b in zip(vector,stored));concepts=json.loads(row['concepts'])
        overlaps=[s for s in concepts if s in query_concepts or (not source and s.lower() in text.lower())]
        lexical=len(overlaps)/max(1,min(4,len(query_concepts)))
        score=.84*cosine+.16*min(1,lexical)
        results.append({'question_id':row['question_id'],'number':row['number'],'paper_title':row['paper_title'] or '本地题目',
                        'subject':row['subject'],'topic':row['topic'],'concepts':concepts,'preview':row['text'][:160],
                        'score':round(score,4),'similarity':round(cosine,4),
                        'reason':'考察方向：'+('、'.join(overlaps) if overlaps else row['topic'])+'；结合知识点与解题方法的向量相似度。'})
    results.sort(key=lambda r:r['score'],reverse=True)
    return {'items':results[:limit],'space':active,'mode':'knowledge_embedding','reason':'按知识方向、理解要点和解题方法检索，分数为排序依据。'}

def stats():
    profile=profiles.selected('embedding');active=space(profile)
    with db.connection() as c:
        total=c.execute('SELECT count(*) FROM questions').fetchone()[0]
        rows=c.execute('SELECT question_id,fingerprint,dimensions FROM question_embeddings WHERE space=?',(active,)).fetchall()
        valid=sum(r['fingerprint']==k.fingerprint(k.bank_question(c,r['question_id'])) for r in rows)
        jobs=[dict(r) for r in c.execute('SELECT id,paper_id,status,phase,total,completed,failed,error,created_at,updated_at FROM embedding_jobs ORDER BY created_at DESC LIMIT 5')]
    return {'indexed':valid,'total':total,'dimensions':rows[0]['dimensions'] if rows else None,'model':profile.model_id,'space':active,
            'ready':ready(profile),'local':profile.protocol=='local_bge','auto_index':profiles.read()['auto_index'],'jobs':jobs}

def enqueue(paper_id=None,ids=None,*,automatic=False):
    if automatic and not profiles.read()['auto_index']:return None
    qs=all_questions(paper_id,ids);ids=[q['id'] for q in qs]
    if not ids:return None
    job_id=uuid.uuid4().hex;stamp=k.now()
    with db.connection() as c:
        # A running full bank job covers individual imports only if its snapshot includes them.
        for row in c.execute("SELECT id,question_ids FROM embedding_jobs WHERE status IN ('queued','running')"):
            if set(ids).issubset(json.loads(row['question_ids'])):return row['id']
        c.execute('INSERT INTO embedding_jobs VALUES(?,?,?,?,?,?,0,0,?,?,?)',(job_id,paper_id,k.dump(ids),'queued','预解析',len(ids),'',stamp,stamp))
    _wake.set();return job_id

def _update(jid,**values):
    values['updated_at']=k.now()
    with db.connection() as c:c.execute('UPDATE embedding_jobs SET '+','.join(key+'=?' for key in values)+' WHERE id=?',(*values.values(),jid))

def process(jid):
    with db.connection() as c:job=dict(c.execute('SELECT * FROM embedding_jobs WHERE id=?',(jid,)).fetchone())
    _update(jid,status='running',phase='预解析',completed=0,failed=0,error='')
    try:
        profile=profiles.selected('embedding')
        if not ready(profile):raise provider.ProviderError('内置向量模型未准备好，任务已保留，准备后点击重试。')
        qs=all_questions(ids=json.loads(job['question_ids']));missing=[q for q in qs if not k.get(q)]
        if missing:
            chat=provider.load_profile()
            for i in range(0,len(missing),2):
                if _stop.is_set():raise provider.ProviderError('任务已暂停，将在下次启动恢复。')
                batch=missing[i:i+2];values,result=k.analyse(batch,chat,cancelled=_stop.is_set)
                for q in batch:k.put(q,values[q['id']],'新导入试卷自动预解析',result['model_id'])
        _update(jid,phase='向量索引')
        result=index_questions(qs,profile,cancelled=_stop.is_set,progress=lambda n:_update(jid,completed=n))
        if result['completed']!=len(qs):raise ValueError('部分题目已修改，请重试以解析新版本。')
        _update(jid,status='complete',phase='完成',completed=len(qs))
    except Exception as exc:
        # Provider errors are already redacted; never write raw HTTP exceptions or credentials.
        message=str(exc) if isinstance(exc,(provider.ProviderError,ValueError)) else '建索引失败，请检查模型依赖与配置后重试。'
        _update(jid,status='queued' if _stop.is_set() else 'failed',failed=1,error=message[:500])

def _loop():
    while not _stop.is_set():
        from ..identity import current_user
        with db.connection(shared=True) as c:user_ids=[r['id'] for r in c.execute('SELECT id FROM users')]
        processed=False
        for user_id in user_ids:
            token=current_user.set(user_id)
            try:
                with db.connection() as c:row=c.execute("SELECT id FROM embedding_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
                if row:process(row['id']);processed=True
            finally:current_user.reset(token)
            if _stop.is_set():break
        if not processed:_wake.wait(2);_wake.clear()

def start():
    global _worker
    if _worker and _worker.is_alive():return
    init();_stop.clear();_wake.clear()
    with db.connection() as c:c.execute("UPDATE embedding_jobs SET status='queued' WHERE status='running'")
    # Test/clean installs with no weights do not silently start paid analysis jobs.
    p=profiles.selected('embedding')
    if profiles.read()['auto_index'] and ready(p):
        state=stats()
        if state['indexed']<state['total']:enqueue()
    _worker=threading.Thread(target=_loop,name='knowledge-embedding',daemon=True);_worker.start()

def stop():
    _stop.set();_wake.set()
    if _worker:_worker.join(timeout=10)

def changed(ids):
    if _worker and _worker.is_alive():
        try:return enqueue(ids=ids,automatic=True)
        except Exception:return None
