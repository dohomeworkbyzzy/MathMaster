"""Route personal study tables; the question bank remains shared.

zzy keeps the original tables, so upgrades never rewrite existing study data.
Other users get empty tables with the same schema and foreign keys. Only SQL
identifiers are routed: bound values, literals and comments are untouched.
"""
import re
import sqlite3

PERSONAL_TABLES = frozenset({
    'attempts', 'practice_visits', 'question_annotations', 'history', 'note_calculations',
    'ai_sessions', 'ai_turns', 'ai_observations', 'exam_runs', 'grade_batches',
    'difficulty_overrides', 'difficulty_outcomes', 'difficulty_progress', 'difficulty_recommendations',
    'answer_submissions', 'grading_answer_images', 'grading_answer_drafts', 'embedding_jobs',
})
_TOKEN = re.compile(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/|\"(?:\"\"|[^\"])*\"|\[[^\]]*\]|`[^`]*`|[A-Za-z_][A-Za-z_0-9]*")


def prefix(user_id):
    if user_id == 'zzy':return ''
    if not re.fullmatch(r'[a-f0-9]{32}', user_id):raise ValueError('无效的用户编号。')
    return 'user_' + user_id + '__'


def route_sql(sql, user_id):
    tag = prefix(user_id)
    if not tag:return sql
    indexes = set(re.findall(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', sql, re.I))
    def replace(match):
        token = match.group()
        if token[0] in ('"', '[', '`'):
            name = token[1:-1]
            return token[0]+tag+name+token[-1] if name.lower() in PERSONAL_TABLES or name in indexes else token
        return tag+token if token.lower() in PERSONAL_TABLES or token in indexes else token
    return _TOKEN.sub(replace, sql)


class UserCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return super().execute(route_sql(sql, self.connection.user_id), parameters)

    def executemany(self, sql, parameters):
        return super().executemany(route_sql(sql, self.connection.user_id), parameters)

    def executescript(self, sql):
        return super().executescript(route_sql(sql, self.connection.user_id))


class UserConnection(sqlite3.Connection):
    user_id = 'zzy'

    def cursor(self, factory=UserCursor):return super().cursor(factory)

    def execute(self, sql, parameters=()):return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):return self.cursor().executemany(sql, parameters)

    def executescript(self, sql):return self.cursor().executescript(sql)


def create_tables(connection, user_id):
    if user_id == 'zzy':return
    schemas = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index') ORDER BY type DESC").fetchall()
    for schema in schemas:
        if schema['tbl_name'] not in PERSONAL_TABLES:continue
        sql = route_sql(schema['sql'], user_id)
        sql = re.sub(r'^CREATE (TABLE|(?:UNIQUE )?INDEX) ', r'CREATE \1 IF NOT EXISTS ', sql, flags=re.I)
        connection.execute(sql)


def filter_backup(connection, user_id):
    """Keep this user's records and the shared bank in a portable backup."""
    tag=prefix(user_id)
    connection.execute('PRAGMA foreign_keys=OFF')
    names=[r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for name in names:
        if re.fullmatch(r'user_[a-f0-9]{32}__\w+',name) and not (tag and name.startswith(tag)):
            connection.execute('DROP TABLE "'+name+'"')
    if tag:
        for name in PERSONAL_TABLES:
            if name in names:connection.execute('DELETE FROM "'+name+'"')
        connection.execute("UPDATE users SET preferences='{}' WHERE id='zzy'")
    connection.execute("DELETE FROM users WHERE id NOT IN ('zzy',?)",(user_id,))
    connection.commit()
    # Purge deleted users' pages as well as their rows from the exported file.
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('VACUUM')
