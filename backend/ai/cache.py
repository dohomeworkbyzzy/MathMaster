"""Disposable SQLite cache; never stores requests, credentials or learner records."""
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from .. import db

MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 5000
_guard = threading.Lock()
_flights = {}

def path(): return db.DATA / 'ai-cache.db'

def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()

@contextmanager
def connection():
    db.DATA.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path(),timeout=10)
    con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA auto_vacuum=INCREMENTAL')
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS entries(namespace TEXT NOT NULL,key TEXT NOT NULL,
          value TEXT NOT NULL,expires REAL NOT NULL,accessed REAL NOT NULL,size INTEGER NOT NULL,
          PRIMARY KEY(namespace,key));
        CREATE INDEX IF NOT EXISTS cache_access ON entries(accessed);
        CREATE TABLE IF NOT EXISTS metrics(namespace TEXT PRIMARY KEY,
          hits INTEGER NOT NULL DEFAULT 0,misses INTEGER NOT NULL DEFAULT 0,
          remote_calls INTEGER NOT NULL DEFAULT 0,prompt_tokens INTEGER NOT NULL DEFAULT 0,
          completion_tokens INTEGER NOT NULL DEFAULT 0,provider_cached_tokens INTEGER NOT NULL DEFAULT 0,
          avoided_prompt_tokens INTEGER NOT NULL DEFAULT 0,avoided_completion_tokens INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,generation INTEGER NOT NULL);
        INSERT OR IGNORE INTO settings VALUES(1,0);
        ''')
        yield con
        con.commit()
    except BaseException:
        con.rollback();raise
    finally:con.close()

def generation():
    try:
        with connection() as con:return con.execute('SELECT generation FROM settings WHERE id=1').fetchone()[0]
    except (sqlite3.Error,OSError):return None

def token_count(usage,name):
    if not isinstance(usage,dict):return 0
    value=usage.get(name,0)
    return max(0,value) if isinstance(value,int) else 0

def get(namespace,cache_key,count_miss=True):
    try:
        with connection() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('INSERT OR IGNORE INTO metrics(namespace) VALUES(?)',(namespace,))
            row=con.execute('SELECT value,expires FROM entries WHERE namespace=? AND key=?',(namespace,cache_key)).fetchone()
            if row and row['expires']>time.time():
                try:value=json.loads(row['value'])
                except ValueError:value=None
                if isinstance(value,dict):
                    usage=value.get('usage',{})
                    con.execute('UPDATE entries SET accessed=? WHERE namespace=? AND key=?',(time.time(),namespace,cache_key))
                    con.execute('''UPDATE metrics SET hits=hits+1,avoided_prompt_tokens=avoided_prompt_tokens+?,
                      avoided_completion_tokens=avoided_completion_tokens+? WHERE namespace=?''',
                      (token_count(usage,'prompt_tokens'),token_count(usage,'completion_tokens'),namespace))
                    return value
            if row:con.execute('DELETE FROM entries WHERE namespace=? AND key=?',(namespace,cache_key))
            if count_miss:con.execute('UPDATE metrics SET misses=misses+1 WHERE namespace=?',(namespace,))
    except (sqlite3.Error,OSError):pass
    return None

def put(namespace,cache_key,value,ttl,generation_at_start):
    serialized=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    size=len(serialized.encode('utf-8'))
    if size>min(MAX_BYTES,2_000_000) or generation_at_start is None:return False
    try:
        with connection() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT generation FROM settings WHERE id=1').fetchone()[0]!=generation_at_start:return False
            con.execute('DELETE FROM entries WHERE expires<=?',(time.time(),))
            con.execute('INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?)',
                        (namespace,cache_key,serialized,time.time()+ttl,time.time(),size))
            count,total=con.execute('SELECT count(*),coalesce(sum(size),0) FROM entries').fetchone()
            if count>MAX_ENTRIES or total>MAX_BYTES:
                for row in con.execute('SELECT namespace,key,size FROM entries ORDER BY accessed').fetchall():
                    if count<=MAX_ENTRIES and total<=MAX_BYTES:break
                    con.execute('DELETE FROM entries WHERE namespace=? AND key=?',(row['namespace'],row['key']))
                    count-=1;total-=row['size']
            con.execute('PRAGMA incremental_vacuum(64)')
        return True
    except (sqlite3.Error,OSError):return False

def record_remote(namespace,usage):
    try:
        with connection() as con:
            con.execute('INSERT OR IGNORE INTO metrics(namespace) VALUES(?)',(namespace,))
            hit=token_count(usage,'prompt_cache_hit_tokens')
            if not hit and isinstance(usage.get('prompt_tokens_details'),dict):
                hit=token_count(usage['prompt_tokens_details'],'cached_tokens')
            con.execute('''UPDATE metrics SET remote_calls=remote_calls+1,prompt_tokens=prompt_tokens+?,
              completion_tokens=completion_tokens+?,provider_cached_tokens=provider_cached_tokens+? WHERE namespace=?''',
              (token_count(usage,'prompt_tokens'),token_count(usage,'completion_tokens'),hit,namespace))
    except (sqlite3.Error,OSError):pass

def stats():
    try:
        with connection() as con:
            con.execute('DELETE FROM entries WHERE expires<=?',(time.time(),))
            rows=[dict(row) for row in con.execute('SELECT * FROM metrics ORDER BY namespace')]
            entries,size=con.execute('SELECT count(*),coalesce(sum(size),0) FROM entries').fetchone()
        names=('hits','misses','remote_calls','prompt_tokens','completion_tokens','provider_cached_tokens',
               'avoided_prompt_tokens','avoided_completion_tokens')
        return {'enabled':True,'entries':entries,'bytes':size,'max_bytes':MAX_BYTES,
                'totals':{n:sum(row[n] for row in rows) for n in names},'categories':rows}
    except (sqlite3.Error,OSError):return {'enabled':False,'entries':0,'bytes':0,'totals':{},'categories':[]}

def clear():
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM entries')
        con.execute('UPDATE settings SET generation=generation+1 WHERE id=1')
        con.execute('PRAGMA incremental_vacuum(4096)')
    return stats()

@contextmanager
def single_flight(namespace,cache_key,cancelled,error):
    """Only one local producer pays for a given request; waiting can be cancelled."""
    identity=(str(path().resolve()),namespace,cache_key)
    with _guard:
        slot=_flights.setdefault(identity,[threading.Lock(),0]);slot[1]+=1
    acquired=False
    try:
        while not acquired:
            if cancelled and cancelled():raise error('本轮已取消，输入保留。')
            acquired=slot[0].acquire(timeout=.1)
        if cancelled and cancelled():raise error('本轮已取消，输入保留。')
        yield
    finally:
        if acquired:slot[0].release()
        with _guard:
            slot[1]-=1
            if not slot[1]:_flights.pop(identity,None)
