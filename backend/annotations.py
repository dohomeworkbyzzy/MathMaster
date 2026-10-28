"""Personal, versioned overlays. Source images and scratch work are untouched."""
import json
import re
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import db

router=APIRouter(prefix='/api/questions')


def has_annotations(qid:str):
    # The bank is shared: merging must also preserve another user's annotations.
    with db.connection(shared=True) as conn:
        tables=[r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if re.fullmatch(r'(?:user_[a-f0-9]{32}__)?question_annotations',r['name'])]
        return any(conn.execute(f'SELECT 1 FROM "{name}" WHERE question_id=? AND strokes!=?',(qid,'[]')).fetchone() for name in tables)


class Point(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    x:float=Field(ge=0,le=1)
    y:float=Field(ge=0,le=1)


class Stroke(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    image:str=Field(min_length=1,max_length=500)
    tool:Literal['pen','highlight']='pen'
    color:Literal['#ff6b6b','#4dabf7','#ffd43b','#51cf66']='#ff6b6b'
    width:float=Field(ge=1,le=30,allow_inf_nan=False)
    points:list[Point]=Field(min_length=1,max_length=10000)


class AnnotationInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=0)
    strokes:list[Stroke]=Field(max_length=2000)

    @model_validator(mode='after')
    def limits(self):
        if sum(len(s.points) for s in self.strokes)>100000:
            raise ValueError('标注过多，请先清理不需要的笔画。')
        if len({s.id for s in self.strokes})!=len(self.strokes):
            raise ValueError('标注笔画编号重复。')
        return self


def exists(conn,qid):
    if not conn.execute('SELECT 1 FROM questions WHERE id=?',(qid,)).fetchone():
        raise HTTPException(404,'题目不存在。')


@router.get('/{qid}/annotations')
def read(qid:str):
    with db.connection() as conn:
        exists(conn,qid)
        row=conn.execute('SELECT version,strokes,updated_at FROM question_annotations WHERE question_id=?',(qid,)).fetchone()
        return {'version':row['version'],'strokes':json.loads(row['strokes']),'updated_at':row['updated_at']} if row else {'version':0,'strokes':[],'updated_at':None}


@router.put('/{qid}/annotations')
def save(qid:str,body:AnnotationInput):
    stamp=datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        exists(conn,qid)
        previous=conn.execute('SELECT version FROM question_annotations WHERE question_id=?',(qid,)).fetchone()
        if body.version!=(previous['version'] if previous else 0):
            raise HTTPException(409,'标注已在其他页面更新。本页未保存的标注仍保留，请先下载标注，再重新打开题目。')
        conn.execute('''INSERT INTO question_annotations VALUES(?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET
          version=excluded.version,strokes=excluded.strokes,updated_at=excluded.updated_at''',
          (qid,body.version+1,json.dumps([s.model_dump() for s in body.strokes],ensure_ascii=False,separators=(',',':')),stamp))
    return {'version':body.version+1,'updated_at':stamp}
