import json
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from .identity import current_user
from .user_storage import UserConnection

DATA=Path(os.environ.get('MATHMASTER_DATA',Path(__file__).resolve().parents[1]/'data'))
@contextmanager
def connection(*,shared=False):
    DATA.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA/'mathmaster.db',timeout=15,factory=UserConnection)
    db.user_id='zzy' if shared else current_user.get()
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback(); raise
    finally: db.close()

def init_db():
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY,title TEXT NOT NULL,subject TEXT NOT NULL,
          filename TEXT NOT NULL,created_at TEXT NOT NULL, warnings TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,paper_id TEXT REFERENCES papers(id),
          number TEXT NOT NULL,text TEXT NOT NULL,images TEXT NOT NULL DEFAULT '[]',reference_answer TEXT NOT NULL DEFAULT '',
          subject TEXT NOT NULL DEFAULT '数学一',confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(question_id TEXT PRIMARY KEY REFERENCES questions(id),
          answer TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',draft TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '未作答',wrong INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS practice_visits(question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
          visited_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS question_annotations(question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,strokes TEXT NOT NULL DEFAULT '[]',updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,question_id TEXT REFERENCES questions(id),
          operation TEXT NOT NULL,request TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS history_question_time ON history(question_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS note_calculations(id TEXT PRIMARY KEY,question_id TEXT NOT NULL REFERENCES questions(id),
          history_id TEXT NOT NULL REFERENCES history(id),created_at TEXT NOT NULL);
        ''')

def decode(row):
    if row is None:return None
    obj=dict(row)
    for key in ('images','warnings','request','result'):
        if key in obj:obj[key]=json.loads(obj[key])
    return obj
