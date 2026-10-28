"""Three named, password-free users sharing the question bank."""
import json
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from . import db
from .identity import current_user
from .user_storage import create_tables

router=APIRouter(prefix='/api/users',tags=['用户'])
COOKIE='mathmaster_user'


def init():
    with db.connection(shared=True) as c:
        c.executescript('''
          CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT UNIQUE NOT NULL,
            preferences TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS users_limit BEFORE INSERT ON users
            WHEN (SELECT count(*) FROM users)>=3 BEGIN SELECT RAISE(ABORT,'user limit'); END;
        ''')
        if not c.execute("SELECT 1 FROM users WHERE id='zzy'").fetchone():
            c.execute('INSERT INTO users(id,name,name_key,created_at) VALUES(?,?,?,?)',('zzy','zzy','zzy',datetime.now(timezone.utc).isoformat()))
        for row in c.execute('SELECT id FROM users').fetchall():create_tables(c,row['id'])


def known(user_id):
    with db.connection(shared=True) as c:
        return bool(c.execute('SELECT 1 FROM users WHERE id=?',(user_id,)).fetchone())


def preferences():
    if not (db.DATA/'mathmaster.db').exists():return {}
    with db.connection(shared=True) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():return {}
        row=c.execute('SELECT preferences FROM users WHERE id=?',(current_user.get(),)).fetchone()
    return json.loads(row['preferences']) if row else {}


def save_preferences(**changes):
    with db.connection(shared=True) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():return False
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT preferences FROM users WHERE id=?',(current_user.get(),)).fetchone()
        if not row:return False
        value={**json.loads(row['preferences']),**changes}
        c.execute('UPDATE users SET preferences=? WHERE id=?',(json.dumps(value,ensure_ascii=False),current_user.get()))
    return True


def selection(response,request,user_id):
    response.set_cookie(COOKIE,user_id,max_age=365*24*60*60,httponly=True,samesite='lax',secure=request.url.scheme=='https')


@router.get('')
def listing():
    with db.connection(shared=True) as c:items=[dict(row) for row in c.execute('SELECT id,name FROM users ORDER BY created_at,id')]
    return {'users':items,'current_user':current_user.get(),'limit':3,'remaining':3-len(items)}


class Register(BaseModel):
    name:str=Field(min_length=1,max_length=24)


@router.post('',status_code=201)
def register(body:Register,request:Request,response:Response):
    name=unicodedata.normalize('NFKC',body.name).strip()
    if not name or len(name)>24 or any(unicodedata.category(ch).startswith('C') for ch in name):
        raise HTTPException(422,'用户名请填写 1–24 个可见字符。')
    user_id=uuid.uuid4().hex
    try:
        with db.connection(shared=True) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM users WHERE name_key=?',(name.casefold(),)).fetchone():raise HTTPException(409,'该用户名已存在，请直接选择。')
            if c.execute('SELECT count(*) FROM users').fetchone()[0]>=3:raise HTTPException(409,'最多三个用户，注册名额已满。')
            c.execute('INSERT INTO users(id,name,name_key,created_at) VALUES(?,?,?,?)',(user_id,name,name.casefold(),datetime.now(timezone.utc).isoformat()))
            create_tables(c,user_id)
    except sqlite3.IntegrityError:raise HTTPException(409,'用户名已存在或三个名额已满。') from None
    selection(response,request,user_id)
    return {'id':user_id,'name':name}


@router.post('/{user_id}/select')
def select(user_id:str,request:Request,response:Response):
    if not known(user_id):raise HTTPException(404,'用户不存在。')
    selection(response,request,user_id)
    return {'id':user_id}
