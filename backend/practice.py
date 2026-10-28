"""Practice entry points; opening a question never changes its saved answer."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from . import db

router=APIRouter(prefix='/api/practice')


@router.get('/recent')
def recent(limit:int=Query(default=6,ge=1,le=20)):
    # Include pre-existing attempts/calculations so upgrades have a useful home page.
    with db.connection() as conn:
        rows=conn.execute('''WITH activity AS (
          SELECT question_id,visited_at AS stamp FROM practice_visits
          UNION ALL SELECT question_id,updated_at FROM attempts
          UNION ALL SELECT question_id,updated_at FROM question_annotations
          UNION ALL SELECT question_id,created_at FROM history WHERE question_id IS NOT NULL
        ), latest AS (SELECT question_id,MAX(stamp) AS last_practiced_at FROM activity GROUP BY question_id)
        SELECT q.id,q.paper_id,q.number,q.subject,substr(q.text,1,400) AS text,q.images,q.confirmed,
          p.title AS paper_title,a.status,a.wrong,l.last_practiced_at
        FROM latest l JOIN questions q ON q.id=l.question_id
          LEFT JOIN papers p ON p.id=q.paper_id LEFT JOIN attempts a ON a.question_id=q.id
        ORDER BY l.last_practiced_at DESC,q.rowid DESC LIMIT ?''',(limit,))
        return [db.decode(row) for row in rows]


@router.post('/{qid}/visit')
def visit(qid:str):
    stamp=datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        if not conn.execute('SELECT 1 FROM questions WHERE id=?',(qid,)).fetchone():
            raise HTTPException(404,'题目不存在。')
        conn.execute('''INSERT INTO practice_visits VALUES(?,?) ON CONFLICT(question_id)
          DO UPDATE SET visited_at=excluded.visited_at''',(qid,stamp))
    return {'id':qid,'visited_at':stamp}


@router.get('/{qid}/neighbor')
def neighbor(qid:str,direction:Literal['previous','next']):
    with db.connection() as conn:
        current=conn.execute('SELECT *,rowid AS row_num FROM questions WHERE id=?',(qid,)).fetchone()
        if not current:raise HTTPException(404,'题目不存在。')
        if current['paper_id']:
            scope='paper_id=?';args=[current['paper_id']]
        else:
            scope='paper_id IS NULL AND subject=?';args=[current['subject']]
        # Match the question-library order, including same-timestamp imported rows.
        time_cmp,row_cmp,order=('<','>','created_at DESC,rowid ASC') if direction=='next' else ('>','<','created_at ASC,rowid DESC')
        row=conn.execute(f'''SELECT id FROM questions WHERE {scope}
          AND (created_at {time_cmp} ? OR (created_at=? AND rowid {row_cmp} ?))
          ORDER BY {order} LIMIT 1''',(*args,current['created_at'],current['created_at'],current['row_num'])).fetchone()
        return {'id':row['id'] if row else None}
