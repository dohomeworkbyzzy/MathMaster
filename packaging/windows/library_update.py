"""State-preserving, offline question-bank package validation and installation (stdlib only)."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import zipfile

PRODUCT = 'mathmaster-library'
MAX_SIZE = 3_000_000_000

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe_name(name):
    p = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or p.is_absolute()
            or any(x in ('', '.', '..') for x in name.split('/'))
            or any(x.rstrip(' .') != x for x in p.parts)
            or any(x.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for x in p.parts)):
        raise ValueError('题库包包含不安全的路径。')
    return name

def read_manifest(archive):
    entries = archive.infolist()
    names = [e.filename for e in entries]
    if len(names) != len({n.casefold() for n in names}) or sum(e.file_size for e in entries) > MAX_SIZE:
        raise ValueError('题库包过大或包含重复文件。')
    if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 5_000_000:
        raise ValueError('题库包缺少有效清单。')
    m = json.loads(archive.read('manifest.json'))
    if m.get('format') != 1 or m.get('product') != PRODUCT or not isinstance(m.get('version'),str):
        raise ValueError('不兼容的题库数据包。')
    files=m.get('files')
    if not isinstance(files,dict) or set(files) != set(names)-{'manifest.json'} or 'plan.json' not in files:
        raise ValueError('题库包文件与清单不一致。')
    for e in entries:
        name=safe_name(e.filename)
        if (e.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError('题库包不能包含符号链接。')
        if name=='manifest.json':continue
        if name!='plan.json' and (not name.startswith('uploads/') or PurePosixPath(name).suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.pdf'}):
            raise ValueError('题库包只能包含导入计划和题目图片/PDF。')
        h=files[name]
        if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):
            raise ValueError('题库包校验信息无效。')
    if archive.getinfo('plan.json').file_size>100_000_000:raise ValueError('导入计划过大。')
    return m

def validate_plan(plan, files):
    papers=plan.get('papers');questions=plan.get('questions')
    if not isinstance(papers,list) or not isinstance(questions,list) or not papers or not questions:
        raise ValueError('题库计划为空。')
    pids={p['id'] for p in papers};qids={q['id'] for q in questions}
    if len(pids)!=len(papers) or len(qids)!=len(questions):raise ValueError('重复题目或试卷 ID。')
    for obj in papers+questions:
        if not isinstance(obj['id'],str) or not 1<=len(obj['id'])<=160:raise ValueError('无效 ID。')
        if obj['subject'] not in ('408','数学一','数学二'):raise ValueError('不支持的科目。')
    refs=set()
    for p in papers:
        for k in ('title','filename'):
            if not isinstance(p[k],str):raise ValueError('试卷字段无效。')
        if p['filename']:refs.add('uploads/'+safe_name(p['filename']))
        if not isinstance(p.get('warnings',[]),list):raise ValueError('试卷提示无效。')
    for q in questions:
        if q['paper_id'] not in pids:raise ValueError('题目没有关联试卷。')
        if not isinstance(q.get('images'),list) or not q['images']:raise ValueError('缺少原题截图。')
        for k in ('number','text','reference_answer'):
            if not isinstance(q[k],str):raise ValueError('题目字段无效。')
        spec=q.get('spec',{})
        if not isinstance(spec,dict):raise ValueError('评分配置无效。')
        if spec.get('kind') not in ('mcq','fill','subjective'):raise ValueError('题目类型无效。')
        if not isinstance(spec.get('max_points'),(int,float)) or not 0<spec['max_points']<=150:raise ValueError('分值无效。')
        for name in q['images']+spec.get('reference_images',[]):refs.add('uploads/'+safe_name(name))
    if not refs<=set(files):raise ValueError('题库包缺少原题或答案附件。')
    return plan

def extract_verified(package, destination, report=print):
    with zipfile.ZipFile(package) as archive:
        m=read_manifest(archive)
        for i,(name,h) in enumerate(m['files'].items(),1):
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(name) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
            if digest(target)!=h:raise ValueError('题库包校验失败：'+name)
            if i%300==0:report(f'校验题库文件 {i}/{len(m["files"])}')
        plan=validate_plan(json.loads((destination/'plan.json').read_text(encoding='utf-8')),m['files'])
    return m,plan

def check_target(data, stage, manifest):
    data=data.resolve()
    for name,h in manifest['files'].items():
        if not name.startswith('uploads/'):continue
        target=data/name
        if not target.resolve().is_relative_to(data):raise ValueError('附件目录指向服务数据目录之外。')
        # Never replace an existing asset, even for a different bank revision.
        if target.exists() and (not target.is_file() or digest(target)!=h):raise ValueError('已有同名附件内容不同：'+name)

def install_plan(data, stage, manifest, plan, report=print):
    """Commit questions, specs and import receipt atomically; never overwrite an existing question."""
    check_target(data,stage,manifest)
    created_assets=[]
    try:
        with closing(sqlite3.connect(data/'mathmaster.db',timeout=30)) as c:
            c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
            try:
                c.execute('CREATE TABLE IF NOT EXISTS question_grading(question_id TEXT PRIMARY KEY REFERENCES questions(id),spec TEXT NOT NULL)')
                c.execute('CREATE TABLE IF NOT EXISTS library_imports(version TEXT PRIMARY KEY,created_at TEXT NOT NULL,receipt TEXT NOT NULL)')
                stamp=datetime.now(timezone.utc).isoformat();created=preserved=filled=0
                for p in plan['papers']:
                    c.execute('INSERT OR IGNORE INTO papers(id,title,subject,filename,created_at,warnings) VALUES(?,?,?,?,?,?)',(p['id'],p['title'],p['subject'],p['filename'],stamp,json.dumps(p.get('warnings',[]),ensure_ascii=False)))
                for q in plan['questions']:
                    existing=c.execute('SELECT paper_id,text,images,reference_answer FROM questions WHERE id=?',(q['id'],)).fetchone()
                    if existing:
                        preserved+=1
                        old=c.execute('SELECT spec FROM question_grading WHERE question_id=?',(q['id'],)).fetchone()
                        oldspec=json.loads(old[0]) if old else {}
                        if (not existing[3] and q['reference_answer'] and existing[0]==q['paper_id']
                                and existing[1]==q['text'] and json.loads(existing[2])==q['images']
                                and not oldspec.get('answer_key') and not oldspec.get('solution')):
                            c.execute('UPDATE questions SET reference_answer=? WHERE id=?',(q['reference_answer'],q['id']))
                            c.execute('INSERT OR REPLACE INTO question_grading(question_id,spec) VALUES(?,?)',(q['id'],json.dumps(q['spec'],ensure_ascii=False)))
                            filled+=1
                        continue
                    c.execute('INSERT INTO questions(id,paper_id,number,text,images,reference_answer,subject,confirmed,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(q['id'],q['paper_id'],q['number'],q['text'],json.dumps(q['images'],ensure_ascii=False),q['reference_answer'],q['subject'],int(q.get('confirmed',False)),stamp))
                    c.execute('INSERT INTO question_grading(question_id,spec) VALUES(?,?)',(q['id'],json.dumps(q['spec'],ensure_ascii=False)));created+=1
                for name in manifest['files']:
                    if not name.startswith('uploads/'):continue
                    target=data/name
                    if target.exists():continue
                    target.parent.mkdir(parents=True,exist_ok=True)
                    # Exclusive creation protects against accidental overwrite.
                    with target.open('xb') as dst:
                        created_assets.append(target)
                        with (stage/name).open('rb') as src:shutil.copyfileobj(src,dst)
                if c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('数据库关联检查未通过。')
                result={'version':manifest['version'],'created':created,'preserved_existing':preserved,'filled_answers':filled,'questions':len(plan['questions']),'ai_generated':sum(q['spec'].get('answer_origin')=='ai_generated' for q in plan['questions']),'missing_answers':sum(not q['reference_answer'] for q in plan['questions'])}
                c.execute('INSERT OR IGNORE INTO library_imports VALUES(?,?,?)',(manifest['version'],stamp,json.dumps(result,ensure_ascii=False)))
                c.commit()
                report(f'题库入库完成：新增 {created} 题，保留已有 {preserved} 题，补齐空答案 {filled} 题。')
                return result
            except BaseException:c.rollback();raise
    except BaseException:
        for path in reversed(created_assets):path.unlink(missing_ok=True)
        raise
