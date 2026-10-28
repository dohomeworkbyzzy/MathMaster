import io
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from . import db
from .practice import router as practice_router
from .annotations import router as annotations_router,has_annotations
from .ai import service as ai_service
from .ai.routes import router as ai_router
from . import grading
from .ai import knowledge
from .ai import vectors
from .ai.vector_routes import router as vector_router
from .jobs import run_job, JobError, ROOT
from .runtime import worker_command
from .touchpad import bridge as touchpad_bridge, status as touchpad_status
from .phonepad import bridge as phonepad_bridge
from .network_access import is_local_management
from . import users
from .identity import current_user


def now():return datetime.now(timezone.utc).isoformat()
def uid():return uuid.uuid4().hex

def question_exists(conn,question_id):
    if question_id and not conn.execute('SELECT 1 FROM questions WHERE id=?',(question_id,)).fetchone():
        raise HTTPException(404,'题目不存在。')

@asynccontextmanager
async def lifespan(app):
    db.init_db(); ai_service.init(); grading.init(); knowledge.init(); vectors.init(); users.init()
    with db.connection(shared=True) as c:user_ids=[r['id'] for r in c.execute("SELECT id FROM users WHERE id!='zzy'")]
    for user_id in user_ids:
        token=current_user.set(user_id)
        try:
            ai_service.init();grading.init();vectors.init()
            with db.connection() as c:c.execute("UPDATE embedding_jobs SET status='queued' WHERE status='running'")
        finally:current_user.reset(token)
    if os.environ.get('MATHMASTER_START_INDEXER','1')!='0':vectors.start()
    (db.DATA/'uploads').mkdir(parents=True,exist_ok=True)
    try:
        yield
    finally:
        vectors.stop()
        ai_service.stop()
        touchpad_bridge.stop()
        phonepad_bridge.stop()

app=FastAPI(title='MathMaster 本地 API',version='0.3.1',lifespan=lifespan)
app.include_router(vector_router)
app.include_router(practice_router)
app.include_router(annotations_router)
app.include_router(users.router)

# Explicit per-installation opt-in for a reverse proxy's public origins.
_network_config = db.DATA / 'network-access.json'
NETWORK_ALLOWED_ORIGINS = frozenset(
    json.loads(_network_config.read_text(encoding='utf-8')).get('allowed_origins', [])
    if _network_config.exists() else []
)

@app.middleware('http')
async def local_only(request:Request,call_next):
    try:
        host=urlsplit('//'+request.headers.get('host','')).hostname
    except ValueError:
        return JSONResponse({'detail':'访问地址无效。'},status_code=403)
    origin=request.headers.get('origin')
    allowed={'http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173','http://localhost:5173'}
    allowed.update(NETWORK_ALLOWED_ORIGINS)
    allowed.update(filter(None,os.environ.get('MATHMASTER_ALLOWED_ORIGINS','').split(',')))
    allowed_hosts={'127.0.0.1','localhost','testserver','::1'}
    allowed_hosts.update(urlsplit(value).hostname for value in allowed)
    if host not in allowed_hosts or (origin and origin not in allowed):
        return JSONResponse({'detail':'本地单用户服务不接受外部来源请求。'},status_code=403)
    path = request.url.path.rstrip('/')
    config_path = any(path == prefix or path.startswith(prefix + '/') for prefix in
                      ('/api/ai/profiles', '/api/ai/provider', '/api/ai/reasoning', '/api/ai/embeddings'))
    parts = path.split('/')
    profile_activation = (request.method == 'POST' and len(parts) == 6 and
                          parts[1:4] == ['api', 'ai', 'profiles'] and parts[4] and parts[5] == 'activate')
    if config_path and not profile_activation and not is_local_management(request):
        if request.method == 'GET' and path == '/api/ai/profiles':
            from .ai import profiles
            result = profiles.public_models()
        elif request.method == 'GET' and path == '/api/ai/provider':
            from .ai.provider import public_profile
            result = {k: v for k, v in public_profile().items() if k in ('configured', 'model_id', 'model_name')}
        else:
            return JSONResponse({'detail': '外网访问仅可查看模型名称和切换 API，请在本机管理配置。'},
                                status_code=403, headers={'Cache-Control': 'no-store'})
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    if int(request.headers.get('content-length','0') or '0')>32*1024*1024:
        return JSONResponse({'detail':'请求体过大，最多 32 MB。'},status_code=413)
    r=await call_next(request)
    if config_path:r.headers['Cache-Control']='no-store'
    r.headers['X-Content-Type-Options']='nosniff';r.headers['Referrer-Policy']='same-origin'
    return r

@app.middleware('http')
async def user_context(request:Request,call_next):
    user_id=request.headers.get('x-mathmaster-user') or request.cookies.get(users.COOKIE,'zzy')
    if user_id!='zzy' and not users.known(user_id):
        return JSONResponse({'detail':'所选用户不存在，请重新选择用户。'},status_code=409)
    token=current_user.set(user_id)
    try:
        response=await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
            response.headers['Vary']='Cookie, X-MathMaster-User'
        return response
    finally:current_user.reset(token)

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question_id:str|None=Field(default=None,max_length=64)
class CalculusInput(Input):
    expression:str=Field(min_length=1,max_length=600)
    variable:str=Field(default='x',max_length=1)
class IntegrateInput(CalculusInput):
    lower:str|None=Field(default=None,max_length=100)
    upper:str|None=Field(default=None,max_length=100)
class DifferentiateInput(CalculusInput):
    functions:list[str]=Field(default_factory=list,max_length=8)
    order:int=Field(default=1,ge=1,le=8)
    variables:list[str]|None=Field(default=None,max_length=8)
class MatrixInput(Input):
    matrix:list[list[str|int|float]]=Field(max_length=8,min_length=1)
    matrix_b:list[list[str|int|float]]|None=Field(default=None,max_length=8)
    action:Literal['add','subtract','multiply','transpose','inverse','determinant','rank','rref','solve']='rref'
    method:Literal['elimination','cofactor']='elimination'

def calculate(operation,body):
    req=body.model_dump(exclude_none=True); qid=req.pop('question_id',None)
    with db.connection() as conn:question_exists(conn,qid)
    try:result=run_job(operation,req)
    except JobError as e:raise HTTPException(422,str(e))
    result['history_id']=uid();result['created_at']=now();result['question_id']=qid
    with db.connection() as conn:
        question_exists(conn,qid)
        conn.execute('INSERT INTO history VALUES(?,?,?,?,?,?)',(result['history_id'],qid,operation,json.dumps(req,ensure_ascii=False),json.dumps(result,ensure_ascii=False),result['created_at']))
    return result

@app.post('/api/math/integrate')
def integrate(body:IntegrateInput):return calculate('integrate',body)
@app.post('/api/math/differentiate')
def differentiate(body:DifferentiateInput):return calculate('differentiate',body)
@app.post('/api/math/matrix')
def matrix(body:MatrixInput):return calculate('matrix',body)
@app.get('/api/math/history')
def history(question_id:str|None=None,workspace:bool=False,limit:int=50,offset:int=0):
    if not 1<=limit<=100 or offset<0:raise HTTPException(422,'分页参数无效。')
    where='';args=[]
    if question_id:where=' WHERE question_id=?';args=[question_id]
    elif workspace:where=' WHERE question_id IS NULL'
    with db.connection() as conn:
        return [db.decode(r) for r in conn.execute('SELECT * FROM history'+where+' ORDER BY created_at DESC LIMIT ? OFFSET ?',(*args,limit,offset))]

@app.get('/api/health')
def health():
    from .importer import tesseract_binary
    return {'status':'ok','local':True,'sympy':'1.14.0','ocr_available':bool(tesseract_binary()),'docx_renderer_available':bool(os.environ.get('LIBREOFFICE_CMD') or shutil.which('libreoffice') or shutil.which('soffice') or (os.name=='nt' and Path(r'C:\Program Files\LibreOffice\program\soffice.exe').exists()))}

@app.get('/api/touchpad/status')
def touchpad_info():return touchpad_status()

@app.post('/api/phonepad/start')
def phonepad_start():
    try:return phonepad_bridge.start()
    except ValueError as e:raise HTTPException(422,str(e))

@app.post('/api/phonepad/stop')
def phonepad_stop(body:dict):
    token=body.get('token')
    if not isinstance(token,str) or len(token)<20:raise HTTPException(422,'无效会话')
    try:phonepad_bridge.stop(token)
    except ValueError as e:raise HTTPException(403,str(e))
    return {'stopped':True}

@app.get('/api/phonepad/events')
def phonepad_events(token:str):
    try:session=phonepad_bridge.get(token)
    except ValueError as e:raise HTTPException(403,str(e))
    return StreamingResponse(phonepad_bridge.events(session),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

class PhonepadControl(BaseModel):
    token:str=Field(min_length=20,max_length=100)
    selected:bool|None=None
    reset:bool=False

@app.post('/api/phonepad/control')
def phonepad_control(body:PhonepadControl):
    try:session=phonepad_bridge.get(body.token)
    except ValueError as e:raise HTTPException(403,str(e))
    with phonepad_bridge.lock:
        session.control={**session.control,
                         'selected':session.control['selected'] if body.selected is None else body.selected,
                         'reset':session.control['reset']+int(body.reset)}
    return {'ok':True}

class WindowMode(BaseModel):
    mode:Literal['compact','restore','minimize']

@app.post('/api/window')
def change_window(body:WindowMode):
    from .desktop_window import change
    try:return change(body.mode)
    except (ValueError,OSError) as e:raise HTTPException(422,str(e))

@app.post('/api/touchpad/start')
def touchpad_start():
    try:return touchpad_bridge.start()
    except Exception as e:raise HTTPException(422,str(e))

class TouchpadToken(BaseModel):
    token:str=Field(min_length=20,max_length=100)

@app.post('/api/touchpad/stop')
def touchpad_stop(body:TouchpadToken):
    try:touchpad_bridge.stop(body.token)
    except ValueError as e:raise HTTPException(403,str(e))
    return {'stopped':True}

@app.get('/api/touchpad/events')
def touchpad_events(token:str):
    try:session=touchpad_bridge.get(token)
    except ValueError as e:raise HTTPException(403,str(e))
    return StreamingResponse(touchpad_bridge.events(session),media_type='text/event-stream',
                             headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

class QuestionInput(BaseModel):
    title:str|None=Field(default=None,max_length=200)
    number:str=Field(default='自建题',max_length=50)
    text:str=Field(min_length=1,max_length=30000)
    subject:Literal['数学一','数学二','数学三','408']='数学一'
    reference_answer:str=Field(default='',max_length=30000)
    confirmed:bool=True

@app.post('/api/questions')
def create_question(body:QuestionInput):
    qid=uid()
    with db.connection() as conn:
        conn.execute('INSERT INTO questions(id,number,text,subject,reference_answer,confirmed,created_at) VALUES(?,?,?,?,?,?,?)',(qid,body.number,body.text,body.subject,body.reference_answer,int(body.confirmed),now()))
    return {'id':qid}

@app.get('/api/questions')
def questions(subject:str|None=None,paper_id:str|None=None,wrong:bool=False,search:str='',offset:int=0,limit:int=100):
    if not 0<=offset or not 1<=limit<=200:raise HTTPException(422,'分页参数无效。')
    clauses=[];args=[]
    if subject:clauses.append('q.subject=?');args.append(subject)
    if paper_id:clauses.append('q.paper_id=?');args.append(paper_id)
    if wrong:clauses.append('a.wrong=1')
    if search:clauses.append('(q.text LIKE ? OR q.number LIKE ? OR p.title LIKE ?)');args.extend(['%'+search+'%']*3)
    sql='''SELECT q.*,p.title AS paper_title,p.filename AS source_filename,a.answer,a.notes,a.draft,a.status,a.wrong,a.updated_at
           FROM questions q LEFT JOIN papers p ON p.id=q.paper_id LEFT JOIN attempts a ON a.question_id=q.id'''
    if clauses:sql+=' WHERE '+' AND '.join(clauses)
    with db.connection() as conn:
        return [db.decode(r) for r in conn.execute(sql+' ORDER BY q.created_at DESC,q.rowid ASC LIMIT ? OFFSET ?',(*args,limit,offset))]

@app.get('/api/questions/{qid}')
def get_question(qid:str):
    with db.connection() as conn:
        question_exists(conn,qid)
        q=db.decode(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone())
        spec=grading.question(conn,qid)['spec']
        q['reference_filename']=spec.get('reference_pdf')
        q['reference_images']=spec.get('reference_images',[])
        if q['paper_id']:
            paper=conn.execute('SELECT filename,title FROM papers WHERE id=?',(q['paper_id'],)).fetchone()
            q['source_filename']=paper['filename'];q['paper_title']=paper['title']
        q['attempt']=dict(conn.execute('SELECT * FROM attempts WHERE question_id=?',(qid,)).fetchone() or {})
        q['calculations']=[db.decode(r) for r in conn.execute('SELECT h.* FROM note_calculations n JOIN history h ON n.history_id=h.id WHERE n.question_id=? ORDER BY n.created_at',(qid,))]
    return q

@app.put('/api/questions/{qid}')
def edit_question(qid:str,body:QuestionInput):
    with db.connection() as conn:
        question_exists(conn,qid)
        conn.execute('UPDATE questions SET number=?,text=?,subject=?,reference_answer=?,confirmed=? WHERE id=?',(body.number,body.text,body.subject,body.reference_answer,int(body.confirmed),qid))
    vectors.changed([qid])
    return {'saved':True}

class AttemptInput(BaseModel):
    answer:str=Field(default='',max_length=50000)
    notes:str=Field(default='',max_length=100000)
    draft:str=Field(default='',max_length=2000000)
    status:Literal['未作答','作答中','已完成']='作答中'
    wrong:bool=False
    expected_updated_at:str|None=None

@app.put('/api/questions/{qid}/attempt')
def save_attempt(qid:str,body:AttemptInput):
    stamp=now()
    with db.connection() as conn:
        question_exists(conn,qid)
        conn.execute('BEGIN IMMEDIATE')
        previous=conn.execute('SELECT updated_at FROM attempts WHERE question_id=?',(qid,)).fetchone()
        if 'expected_updated_at' in body.model_fields_set and body.expected_updated_at!=(previous['updated_at'] if previous else None):
            raise HTTPException(409,'此题记录已在其他窗口更新，当前草稿已保留在浏览器；请先导出或复制笔记，再重新打开该题。')
        conn.execute('''INSERT INTO attempts VALUES(?,?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET
          answer=excluded.answer,notes=excluded.notes,draft=excluded.draft,status=excluded.status,wrong=excluded.wrong,updated_at=excluded.updated_at''',
          (qid,body.answer,body.notes,body.draft,body.status,int(body.wrong),stamp))
    return {'saved':True,'updated_at':stamp}

@app.post('/api/questions/{qid}/calculations/{history_id}')
def insert_calculation(qid:str,history_id:str):
    with db.connection() as conn:
        question_exists(conn,qid)
        h=conn.execute('SELECT question_id FROM history WHERE id=?',(history_id,)).fetchone()
        if not h:raise HTTPException(404,'计算记录不存在。')
        if h['question_id']!=qid:raise HTTPException(409,'计算记录属于另一题或独立工作台，请在当前题目重新计算。')
        if not conn.execute('SELECT 1 FROM note_calculations WHERE question_id=? AND history_id=?',(qid,history_id)).fetchone():
            conn.execute('INSERT INTO note_calculations VALUES(?,?,?,?)',(uid(),qid,history_id,now()))
    return {'saved':True}

class SplitInput(BaseModel):
    position:int=Field(ge=1)
@app.post('/api/questions/{qid}/split')
def split_question(qid:str,body:SplitInput):
    new_id=uid()
    with db.connection() as conn:
        question_exists(conn,qid);q=db.decode(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone())
        if body.position>=len(q['text']):raise HTTPException(422,'请将光标放在题目文字中间。')
        conn.execute('UPDATE questions SET text=?,confirmed=0 WHERE id=?',(q['text'][:body.position],qid))
        conn.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',(new_id,q['paper_id'],q['number']+'·拆分',q['text'][body.position:],json.dumps(q['images']), '',q['subject'],0,now()))
    vectors.changed([qid,new_id])
    return {'id':new_id,'warning':'拆分后的题目保留同一原始截图；可使用截图裁切工具调整。'}

class MergeInput(BaseModel):
    other_id:str
@app.post('/api/questions/{qid}/merge')
def merge_question(qid:str,body:MergeInput):
    if body.other_id==qid:raise HTTPException(422,'不能合并自身。')
    with db.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        question_exists(conn,qid);question_exists(conn,body.other_id)
        a=db.decode(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone());b=db.decode(conn.execute('SELECT * FROM questions WHERE id=?',(body.other_id,)).fetchone())
        if a['paper_id']!=b['paper_id']:raise HTTPException(422,'只能合并同一试卷中的题目。')
        if has_annotations(body.other_id):raise HTTPException(409,'被合并题已有题目标注，为保留标注记录暂不允许合并。')
        # Require unattempted source: editing review must never discard study records.
        if conn.execute('SELECT 1 FROM attempts WHERE question_id=?',(body.other_id,)).fetchone() or conn.execute('SELECT 1 FROM history WHERE question_id=?',(body.other_id,)).fetchone():
            raise HTTPException(409,'被合并题已有作答或计算记录，为避免丢失记录暂不允许合并。')
        if (conn.execute('SELECT 1 FROM answer_submissions WHERE question_id=?',(body.other_id,)).fetchone()
            or conn.execute('SELECT 1 FROM grading_answer_images WHERE question_id=?',(body.other_id,)).fetchone()
            or conn.execute('SELECT 1 FROM ai_sessions WHERE question_id=?',(body.other_id,)).fetchone()
            or conn.execute('SELECT 1 FROM exam_runs WHERE instr(snapshot,?)>0',(json.dumps(body.other_id),)).fetchone()):
            raise HTTPException(409,'被合并题已有答案、AI 或整卷记录，为保留历史暂不允许合并。')
        conn.execute('DELETE FROM question_knowledge WHERE question_id IN (?,?)',(qid,body.other_id))
        conn.execute('DELETE FROM question_embeddings WHERE question_id IN (?,?)',(qid,body.other_id))
        conn.execute('DELETE FROM knowledge_failures WHERE question_id IN (?,?)',(qid,body.other_id))
        conn.execute('DELETE FROM question_grading WHERE question_id IN (?,?)',(qid,body.other_id))
        conn.execute('DELETE FROM grading_rules WHERE question_id IN (?,?)',(qid,body.other_id))
        conn.execute('DELETE FROM grading_answer_drafts WHERE question_id=?',(body.other_id,))
        images=list(dict.fromkeys(a['images']+b['images']))
        conn.execute('UPDATE questions SET text=?,images=?,reference_answer=?,confirmed=0 WHERE id=?',(a['text']+'\n'+b['text'],json.dumps(images),a['reference_answer']+'\n'+b['reference_answer'],qid))
        conn.execute('DELETE FROM questions WHERE id=?',(body.other_id,))
    vectors.changed([qid])
    return {'saved':True}

class CropInput(BaseModel):
    image:str=Field(max_length=200)
    top:float=Field(ge=0,lt=1)
    bottom:float=Field(gt=0,le=1)
@app.post('/api/questions/{qid}/crop')
def crop_question(qid:str,body:CropInput):
    from PIL import Image
    if body.bottom<=body.top:raise HTTPException(422,'下边界必须大于上边界。')
    with db.connection() as conn:
        question_exists(conn,qid);q=db.decode(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone())
        if body.image not in q['images']:raise HTTPException(422,'截图不属于当前题目。')
        path=(db.DATA/'uploads'/body.image).resolve(); base=(db.DATA/'uploads').resolve()
        if not path.is_relative_to(base) or not path.exists():raise HTTPException(404,'截图不存在。')
        new_name=path.parent.name+'/'+uid()+'.png'
        with Image.open(path) as im:
            height=im.height
            if int(body.bottom*height)-int(body.top*height)<5:raise HTTPException(422,'裁切区域过小。')
            im.crop((0,int(body.top*height),im.width,int(body.bottom*height))).save(base/new_name)
        images=[new_name if i==body.image else i for i in q['images']]
        conn.execute('UPDATE questions SET images=?,confirmed=0 WHERE id=?',(json.dumps(images),qid))
    vectors.changed([qid])
    return {'saved':True,'original_preserved':True}

IMPORT_SLOT=threading.BoundedSemaphore(1)
@app.post('/api/papers/import')
def import_paper(file:UploadFile=File(...),subject:str=Form('数学一'),title:str=Form('')):
    if subject not in ('数学一','数学二','数学三','408'):raise HTTPException(422,'试卷科目无效。')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf','.docx'):raise HTTPException(422,'支持 PDF（含扫描版）和 DOCX。')
    if not IMPORT_SLOT.acquire(blocking=False):raise HTTPException(409,'已有导入任务，请稍后再试。')
    paper_id=uid();folder=db.DATA/'uploads'/paper_id;folder.mkdir(parents=True)
    path=folder/('source'+suffix); proc=None
    try:
        size=0
        with path.open('wb') as output:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>30*1024*1024:raise HTTPException(413,'单个文件最多 30 MB。')
                output.write(chunk)
        proc=subprocess.Popen(worker_command('backend.importer'),cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try: stdout,_=proc.communicate(json.dumps({'path':str(path.resolve())}),timeout=120)
        except subprocess.TimeoutExpired:
            if os.name=='nt':subprocess.run(['taskkill','/F','/T','/PID',str(proc.pid)],capture_output=True)
            else:os.killpg(proc.pid,signal.SIGKILL)
            proc.communicate();raise HTTPException(422,'试卷导入超时，请减少页数。')
        if proc.returncode or len(stdout)>10_000_000:raise HTTPException(422,'导入进程失败或内容过大，请检查文件。')
        parsed=json.loads(stdout)
        if not parsed['ok']:raise HTTPException(422,parsed['error'])
        stamp=now()
        with db.connection() as conn:
            conn.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',(paper_id,(title or Path(file.filename or '试卷').stem)[:200],subject,paper_id+'/'+path.name,stamp,json.dumps(parsed['warnings'],ensure_ascii=False)))
            for q in parsed['questions']:
                images=[paper_id+'/'+i for i in q['images']]
                conn.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',(uid(),paper_id,q['number'],q['text'][:30000],json.dumps(images),'',subject,0,stamp))
        result={'id':paper_id,'count':len(parsed['questions']),'warnings':parsed['warnings']}
        # Index failures must never roll back a successful import or remove its source images.
        try:result['embedding_job']=vectors.enqueue(paper_id,automatic=True)
        except Exception:result['warnings'].append('试卷已保存，自动知识索引未排队；可在 API 配置中手动重试。')
        return result
    except BaseException:
        shutil.rmtree(folder,ignore_errors=True);raise
    finally:
        file.file.close();IMPORT_SLOT.release()

@app.get('/api/papers')
def papers():
    with db.connection() as conn:
        return [db.decode(r) for r in conn.execute('SELECT p.*,count(q.id) AS count FROM papers p LEFT JOIN questions q ON q.paper_id=p.id GROUP BY p.id ORDER BY p.created_at DESC')]

@app.get('/api/files/{filename:path}')
def uploaded_file(filename:str):
    base=(db.DATA/'uploads').resolve();path=(base/filename).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.pdf','.docx'):raise HTTPException(404,'文件不存在。')
    if filename.startswith('answer-images/'):
        with db.connection() as c:
            if not c.execute('SELECT 1 FROM grading_answer_images WHERE filename=?',(filename,)).fetchone():raise HTTPException(404,'作答图片不存在。')
    return FileResponse(path)

@app.get('/api/backup')
def backup():
    # SQLite backup handles an active WAL correctly; include every original asset.
    with tempfile.TemporaryDirectory() as tmp:
        target=sqlite3.connect(Path(tmp)/'mathmaster.db')
        try:
            with db.connection() as source:source.backup(target)
            from .user_storage import filter_backup
            filter_backup(target,current_user.get())
        finally:target.close()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(Path(tmp)/'mathmaster.db','mathmaster.db')
            uploads=db.DATA/'uploads'
            with db.connection() as c:answer_files={r['filename'] for r in c.execute('SELECT filename FROM grading_answer_images')}
            for f in uploads.rglob('*'):
                relative=f.relative_to(uploads)
                if relative.parts[0]=='answer-images' and relative.as_posix() not in answer_files:continue
                if f.is_file() and 'lo-profile' not in f.parts:archive.write(f,Path('uploads')/relative)
        sources=db.DATA/'sources'
        if sources.exists():
            with zipfile.ZipFile(out,'a',zipfile.ZIP_DEFLATED) as archive:
                for f in sources.rglob('*'):
                    if f.is_file():archive.write(f,Path('sources')/f.relative_to(sources))
        out.seek(0)
    return StreamingResponse(out,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="mathmaster-backup.zip"'})

app.include_router(ai_router)
app.include_router(grading.router)

DIST=ROOT/'dist'
if (DIST/'assets').exists():app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
if (DIST/'mathlive').exists():app.mount('/mathlive',StaticFiles(directory=DIST/'mathlive'),name='mathlive')
@app.get('/mobile')
@app.get('/')
def index():
    if not (DIST/'index.html').exists():return JSONResponse({'detail':'前端尚未构建，请先 npm run build，或启动 npm run dev。'},status_code=503)
    return FileResponse(DIST/'index.html')

@app.get('/api/stats')
def stats():
    with db.connection() as conn:
        return {'questions':conn.execute('SELECT count(*) FROM questions').fetchone()[0],
          'papers':conn.execute('SELECT count(*) FROM papers').fetchone()[0],
          'completed':conn.execute("SELECT count(*) FROM attempts WHERE status='已完成'").fetchone()[0],
          'wrong':conn.execute('SELECT count(*) FROM attempts WHERE wrong=1').fetchone()[0],
          'calculations':conn.execute('SELECT count(*) FROM history').fetchone()[0]}
