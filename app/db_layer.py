from __future__ import annotations

import os
import re
import sqlite3
import datetime as dt
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SQLITE_PATH = Path(os.environ.get('CRM_DB_PATH', str(ROOT / 'commerce_crm.sqlite')))
DATABASE_URL = os.environ.get('DATABASE_URL','').strip()
USING_POSTGRES = DATABASE_URL.lower().startswith(('postgres://','postgresql://'))

_REPLACE_KEYS = {
    'settings': ['setting_key'],
    'm4_meta': ['key'],
    'm41_suppressed_endpoints': ['channel','endpoint'],
}


def _replace_qmarks(sql: str) -> str:
    out=[]; quote=None; i=0
    while i < len(sql):
        ch=sql[i]
        if quote:
            out.append(ch)
            if ch==quote:
                if i+1<len(sql) and sql[i+1]==quote:
                    out.append(sql[i+1]);i+=2;continue
                quote=None
            i+=1;continue
        if ch in "'\"":
            quote=ch;out.append(ch);i+=1;continue
        out.append('%s' if ch=='?' else ch);i+=1
    return ''.join(out)


def _static_datetime_repl(match: re.Match) -> str:
    sign=match.group(1); amount=int(match.group(2)); unit=match.group(3).lower()
    op='+' if sign=='+' else '-'
    return f"(CURRENT_TIMESTAMP {op} INTERVAL '{amount} {unit}')"


def _static_date_repl(match: re.Match) -> str:
    sign=match.group(1); amount=int(match.group(2)); unit=match.group(3).lower()
    op='+' if sign=='+' else '-'
    return f"(CURRENT_DATE {op} INTERVAL '{amount} {unit}')::date"


def _replace_insert_or_replace(sql: str) -> str:
    m=re.match(r'\s*INSERT\s+OR\s+REPLACE\s+INTO\s+([\w\"]+)\s*(\([^)]*\))?\s+VALUES\s*(\(.+\))\s*;?\s*$',sql,re.I|re.S)
    if not m:
        return sql
    raw_table=m.group(1); table=raw_table.strip('"'); cols_part=m.group(2); vals=m.group(3)
    keys=_REPLACE_KEYS.get(table)
    if not keys:
        raise RuntimeError(f'PostgreSQL compatibility needs an explicit upsert key for table {table}.')
    if cols_part:
        cols=[c.strip().strip('"') for c in cols_part[1:-1].split(',')]
    else:
        # Known legacy tables where the complete column order is stable.
        cols = {'settings':['setting_key','setting_value'], 'm4_meta':['key','value']}[table]
        cols_part='('+','.join(cols)+')'
    update=[c for c in cols if c not in keys]
    conflict=','.join(keys)
    if update:
        set_sql=', '.join(f'{c}=EXCLUDED.{c}' for c in update)
        tail=f' ON CONFLICT ({conflict}) DO UPDATE SET {set_sql}'
    else:
        tail=f' ON CONFLICT ({conflict}) DO NOTHING'
    return f'INSERT INTO {raw_table}{cols_part} VALUES {vals}{tail}'



def _translate_ddl_types(sql: str) -> str:
    """Make SQLite-oriented CREATE TABLE DDL valid and useful on PostgreSQL."""
    if not re.match(r'^\s*CREATE\s+TABLE', sql, re.I):
        return sql
    s=sql
    s=re.sub(r'\bBLOB\b','BYTEA',s,flags=re.I)
    # Application timestamps are stored as text in SQLite. PostgreSQL needs a
    # real temporal type so leases/schedules can compare them to CURRENT_TIMESTAMP.
    timestamp_name=r'[A-Za-z_][A-Za-z0-9_]*(?:_at|_until)'
    s=re.sub(rf'\b({timestamp_name})\s+TEXT\b',r'\1 TIMESTAMPTZ',s,flags=re.I)
    return s

def postgres_sql(sql: str) -> str:
    """Translate the small SQLite dialect used by this application to PostgreSQL.

    The function is deliberately narrow and testable. Unsupported SQLite-only
    constructs raise rather than silently changing behaviour.
    """
    s=sql.strip()
    # SQLite's BEGIN IMMEDIATE acquires a write lock eagerly. PostgreSQL has
    # no IMMEDIATE transaction mode; a normal BEGIN is the compatible
    # transaction boundary and row/write locks are acquired by the statements.
    if re.fullmatch(r'BEGIN\s+IMMEDIATE\s*;?',s,re.I):
        return 'BEGIN'
    s=_translate_ddl_types(s)
    if re.match(r'^pragma\s+table_info\s*\(',s,re.I):
        table=re.search(r'pragma\s+table_info\s*\(([^)]+)\)',s,re.I).group(1).strip().strip('"\'')
        return ("SELECT column_name AS name,data_type AS type,is_nullable AS notnull,column_default AS dflt_value,"
                "ordinal_position AS cid FROM information_schema.columns "
                f"WHERE table_schema='public' AND table_name='{table.replace(chr(39),chr(39)*2)}' ORDER BY ordinal_position")
    if re.match(r'^pragma\s+',s,re.I):
        # busy_timeout/foreign_keys are SQLite connection settings and have no SQL equivalent here.
        return 'SELECT 1'

    if re.search(r'INSERT\s+OR\s+REPLACE',s,re.I):
        s=_replace_insert_or_replace(s)
    if re.search(r'INSERT\s+OR\s+IGNORE',s,re.I):
        s=re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', s, flags=re.I)
        s=re.sub(r';\s*$','',s)
        s += ' ON CONFLICT DO NOTHING'

    # SQLite date/time idioms used by the CRM.
    s=re.sub(r"datetime\(\s*'now'\s*,\s*'([+-])(\d+)\s+(minute|minutes|hour|hours|day|days)'\s*\)",_static_datetime_repl,s,flags=re.I)
    s=re.sub(r"date\(\s*'now'\s*,\s*'([+-])(\d+)\s+(minute|minutes|hour|hours|day|days)'\s*\)",_static_date_repl,s,flags=re.I)
    s=re.sub(r"datetime\(\s*'now'\s*,\s*\?\s*\)","(CURRENT_TIMESTAMP + (? )::interval)",s,flags=re.I)
    s=re.sub(r"date\(\s*'now'\s*,\s*\?\s*\)","(CURRENT_DATE + (? )::interval)::date",s,flags=re.I)
    s=re.sub(r"datetime\(\s*'now'\s*\)","CURRENT_TIMESTAMP",s,flags=re.I)
    s=re.sub(r"date\(\s*'now'\s*\)","CURRENT_DATE",s,flags=re.I)
    s=re.sub(r"datetime\(\s*([\w\.]+)\s*\)",r"CAST(\1 AS timestamp)",s,flags=re.I)
    s=re.sub(r"date\(\s*([\w\.()]+)\s*\)",r"CAST(\1 AS date)",s,flags=re.I)
    s=re.sub(r"julianday\(\s*[\"']now[\"']\s*\)\s*-\s*julianday\(\s*([\w\.]+)\s*\)",r"(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - CAST(\1 AS timestamp))) / 86400.0)",s,flags=re.I)
    s=re.sub(r"json_extract\(\s*([\w\.]+)\s*,\s*'\$\.([\w-]+)'\s*\)",r"(CAST(\1 AS jsonb)->>'\2')",s,flags=re.I)
    # SQLite supports scalar max(a,b)/min(a,b); PostgreSQL uses GREATEST/LEAST.
    # Translate only multi-argument calls so aggregate max(column)/min(column) keep their meaning.
    s=re.sub(r'\bmax\(\s*([^,()]+(?:\([^()]*\)[^,()]*)?)\s*,\s*([^()]+(?:\([^()]*\)[^()]*)?)\)',r'GREATEST(\1,\2)',s,flags=re.I)
    s=re.sub(r'\bmin\(\s*([^,()]+(?:\([^()]*\)[^,()]*)?)\s*,\s*([^()]+(?:\([^()]*\)[^()]*)?)\)',r'LEAST(\1,\2)',s,flags=re.I)
    s=re.sub(r'\s+COLLATE\s+NOCASE','',s,flags=re.I)
    s=re.sub(r'DEFAULT\s+\"([^\"]*)\"',lambda m:"DEFAULT '"+m.group(1).replace("'","''")+"'",s,flags=re.I)
    s=s.replace('AUTOINCREMENT','')
    return _replace_qmarks(s)


class HybridRow(dict):
    """Mapping row compatible with sqlite3.Row's string and integer access."""
    def __getitem__(self,key):
        if isinstance(key,int):
            try:return list(self.values())[key]
            except IndexError:raise IndexError(key) from None
        return super().__getitem__(key)


def _normalise_pg_value(value):
    if isinstance(value,dt.datetime):
        if value.tzinfo is not None:
            value=value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value.isoformat(sep=' ',timespec='seconds')
    if isinstance(value,dt.date):return value.isoformat()
    if isinstance(value,memoryview):return bytes(value)
    return value


def _normalise_pg_row(row):
    if row is None:return None
    if isinstance(row,dict):return HybridRow((k,_normalise_pg_value(v)) for k,v in row.items())
    return row


class PostgresCursor:
    def __init__(self,cur):self._cur=cur
    @property
    def rowcount(self):return self._cur.rowcount
    @property
    def description(self):return self._cur.description
    def fetchone(self):return _normalise_pg_row(self._cur.fetchone())
    def fetchall(self):return [_normalise_pg_row(r) for r in self._cur.fetchall()]
    def __iter__(self):
        for row in self._cur:yield _normalise_pg_row(row)


class PostgresConnection:
    def __init__(self, conn): self._conn=conn
    def __enter__(self): return self
    def __exit__(self, typ, value, tb):
        if typ is None: self._conn.commit()
        else: self._conn.rollback()
        self._conn.close(); return False
    def execute(self, sql: str, args=()):
        cur=self._conn.cursor();cur.execute(postgres_sql(sql),tuple(args));return PostgresCursor(cur)
    def executemany(self, sql: str, seq):
        cur=self._conn.cursor();cur.executemany(postgres_sql(sql),seq);return PostgresCursor(cur)
    def executescript(self, script: str):
        # Application schema strings are simple DDL/DML scripts without procedural blocks.
        statements=[];buf=[];quote=None
        for ch in script:
            if quote:
                buf.append(ch)
                if ch==quote: quote=None
                continue
            if ch in "'\"":quote=ch;buf.append(ch);continue
            if ch==';':
                stmt=''.join(buf).strip();buf=[]
                if stmt:statements.append(stmt)
            else:buf.append(ch)
        tail=''.join(buf).strip()
        if tail:statements.append(tail)
        cur=self._conn.cursor()
        for stmt in statements:cur.execute(postgres_sql(stmt))
        return PostgresCursor(cur)
    def commit(self): return self._conn.commit()
    def rollback(self): return self._conn.rollback()
    def close(self): return self._conn.close()

def connect(sqlite_path: Path | str | None = None):
    if not USING_POSTGRES:
        path=Path(sqlite_path) if sqlite_path is not None else Path(SQLITE_PATH)
        con=sqlite3.connect(path,timeout=15)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA busy_timeout=15000')
        con.execute('PRAGMA foreign_keys=ON')
        return con
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError('PostgreSQL mode requires psycopg. Start V14 normally so its private runtime can install requirements.') from exc
    conn=psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=10)
    return PostgresConnection(conn)


def rows(sql: str,args=()):
    with connect() as con:return [dict(r) for r in con.execute(sql,args)]


def one(sql: str,args=()):
    data=rows(sql,args);return data[0] if data else None


def backend_name()->str:return 'postgresql' if USING_POSTGRES else 'sqlite'


def database_ready()->tuple[bool,str]:
    try:
        with connect() as con:
            row=con.execute('SELECT 1 AS ok').fetchone()
        return True,backend_name()
    except Exception as exc:return False,str(exc)


def table_exists(name:str)->bool:
    try:
        if USING_POSTGRES:
            row=one("SELECT count(*) n FROM information_schema.tables WHERE table_schema='public' AND table_name=?",(name,))
            return bool(row and int(row['n'])>0)
        with connect() as con:
            return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
    except Exception:return False

def bootstrap_base_schema()->None:
    if table_exists('contacts'):return
    schema=(ROOT/'production'/'base_schema_postgres.sql').read_text() if USING_POSTGRES else (ROOT/'production'/'base_schema_sqlite.sql').read_text()
    with connect() as con:con.executescript(schema)


def is_database_error(exc:BaseException)->bool:
    if isinstance(exc,sqlite3.Error):return True
    try:
        import psycopg
        return isinstance(exc,psycopg.Error)
    except Exception:return False
