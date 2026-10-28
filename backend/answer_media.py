"""Persistent answer photos. Separate from question images and handwritten workspace drafts."""
import hashlib
import io
import json
import warnings
from pathlib import Path
from PIL import Image,UnidentifiedImageError
from fastapi import HTTPException
from . import db

def init():
    with db.connection() as c:c.executescript('''
      CREATE TABLE IF NOT EXISTS grading_answer_images(id TEXT PRIMARY KEY,question_id TEXT NOT NULL REFERENCES questions(id),
       filename TEXT NOT NULL,sha256 TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS grading_answer_drafts(question_id TEXT PRIMARY KEY REFERENCES questions(id),
       images TEXT NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS grading_rules(question_id TEXT PRIMARY KEY REFERENCES questions(id),payload TEXT NOT NULL);
    ''')

def safe_path(filename):
    uploads=(db.DATA/'uploads').resolve();path=(uploads/filename).resolve()
    if not path.is_relative_to(uploads):raise HTTPException(422,'作答图片路径无效。')
    return path

def resolve(c,qid,ids):
    if len(ids)>5 or len(set(ids))!=len(ids):raise HTTPException(422,'每题最多五张不同作答图片。')
    entries=[]
    for iid in ids:
        row=c.execute('SELECT * FROM grading_answer_images WHERE id=? AND question_id=?',(iid,qid)).fetchone()
        if not row:raise HTTPException(422,'作答图片不存在或属于其他题目。')
        item=dict(row);path=safe_path(item['filename'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise HTTPException(409,'作答图片已变化或丢失，请重新上传。')
        entries.append({**item,'url':'/api/files/'+item['filename']})
    return entries

def normalize(content):
    if not content or len(content)>10*1024*1024:raise HTTPException(413,'每张作答图片最多 10 MB。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>24_000_000:raise ValueError()
                from PIL import ImageOps
                image=ImageOps.exif_transpose(image)
                if image.mode in ('RGBA','LA') or 'transparency' in image.info:
                    rgba=image.convert('RGBA');white=Image.new('RGBA',rgba.size,'white');white.alpha_composite(rgba);image=white.convert('RGB')
                else:image=image.convert('RGB')
                image.thumbnail((2400,3600));image.load();output=io.BytesIO();image.save(output,'PNG')
                return output.getvalue(),image.width,image.height
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise HTTPException(422,'请上传清晰的 PNG、JPEG 或 WebP 图片，像素总量不超过 2400 万。') from None

def draft(c,qid):
    row=c.execute('SELECT * FROM grading_answer_drafts WHERE question_id=?',(qid,)).fetchone()
    return {'version':row['version'] if row else 0,'images':resolve(c,qid,json.loads(row['images'])) if row else []}
