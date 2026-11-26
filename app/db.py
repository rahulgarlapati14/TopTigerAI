"""Database adapter: SQLite locally, PostgreSQL when DATABASE_URL is set."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATABASE_URL = os.getenv('DATABASE_URL', '')
DATA_DIR = Path(os.getenv('TOPTIGER_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'data')))
DB_PATH = DATA_DIR / 'toptiger.sqlite3'
UPLOAD_DIR = DATA_DIR / 'uploads'
IS_POSTGRES = DATABASE_URL.startswith(('postgresql://', 'postgres://'))


class Adapter:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, params=()):
        if IS_POSTGRES:
            if query.strip().upper() == 'BEGIN IMMEDIATE':
                query = 'BEGIN'
            query = query.replace('?', '%s')
        return self.raw.execute(query, params)


@contextmanager
def connection():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as raw:
            yield Adapter(raw)
    else:
        raw = sqlite3.connect(DB_PATH, timeout=10)
        raw.row_factory = sqlite3.Row
        raw.execute('PRAGMA busy_timeout=10000')
        raw.execute('PRAGMA journal_mode=WAL')
        try:
            yield Adapter(raw)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()


def columns(con, table):
    if IS_POSTGRES:
        rows = con.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?', (table,)).fetchall()
        return {row['column_name'] for row in rows}
    return {row[1] for row in con.execute(f'PRAGMA table_info({table})')}
