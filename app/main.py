"""TopTigerAI: local demo API. Not production-ready for real gyms."""
import os
import secrets
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('TOPTIGER_DATA_DIR', str(ROOT / 'data')))
DB_PATH = DATA_DIR / 'toptiger.sqlite3'
UPLOAD_DIR = DATA_DIR / 'uploads'
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
STATION_ID = os.environ.get('TOPTIGER_STATION_ID', 'demo-station')

app = FastAPI(title='TopTigerAI', version='0.1.0')
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=10000')
    con.execute('PRAGMA journal_mode=WAL')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with connection() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            station_id TEXT NOT NULL,
            consent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            video_path TEXT,
            video_bytes INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            result_json TEXT,
            lead_arm TEXT NOT NULL DEFAULT 'left'
        )''')
        columns = {r[1] for r in con.execute('PRAGMA table_info(sessions)')}
        if 'lead_arm' not in columns:
            con.execute("ALTER TABLE sessions ADD COLUMN lead_arm TEXT NOT NULL DEFAULT 'left'")


init_db()


class SessionCreate(BaseModel):
    station_id: str = Field(min_length=1, max_length=100)
    consent: bool
    lead_arm: Literal['left', 'right'] = 'left'


def find_session(session_id: str, token: str):
    with connection() as con:
        row = con.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    if row is None or not secrets.compare_digest(row['access_token'], token):
        raise HTTPException(404, 'Session not found')
    return dict(row)


def require_token(x_session_token: str = Header(default='')):
    if not x_session_token:
        raise HTTPException(401, 'Session token required')
    return x_session_token


@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/api/sessions', status_code=201)
def create_session(body: SessionCreate):
    if body.station_id != STATION_ID:
        raise HTTPException(404, 'Unknown station')
    if body.consent is not True:
        raise HTTPException(422, 'Recording consent required')
    sid, token, now = str(uuid4()), secrets.token_urlsafe(32), utcnow()
    with connection() as con:
        con.execute('''INSERT INTO sessions
            (id,access_token,station_id,consent_at,status,created_at,updated_at,lead_arm)
            VALUES (?,?,?,?,?,?,?,?)''',
            (sid, token, body.station_id, now, 'created', now, now, body.lead_arm))
    return {'session_id': sid, 'session_token': token, 'status': 'created'}


@app.get('/api/sessions/{session_id}')
def session_status(session_id: str, token: str = Depends(require_token)):
    row = find_session(session_id, token)
    import json
    return {
        'session_id': row['id'], 'status': row['status'],
        'created_at': row['created_at'],
        'result': json.loads(row['result_json']) if row['result_json'] else None,
    }


def video_format(head: bytes):
    if len(head) >= 12 and head[4:8] == b'ftyp':
        return '.mp4'
    if head.startswith(b'\x1a\x45\xdf\xa3'):
        return '.webm'
    return None


@app.post('/api/sessions/{session_id}/video', status_code=202)
async def upload_video(session_id: str, video: UploadFile, token: str = Depends(require_token)):
    find_session(session_id, token)
    if video.content_type not in ('video/mp4', 'video/webm'):
        raise HTTPException(415, 'Only MP4 or WebM is supported')
    tmp_path = UPLOAD_DIR / f'{session_id}.{secrets.token_hex(8)}.tmp'
    size = 0
    head = b''
    try:
        with tmp_path.open('wb') as out:
            while chunk := await video.read(1024 * 1024):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'Maximum video size is 25 MB')
                out.write(chunk)
        suffix = video_format(head)
        if size == 0 or suffix is None or (suffix == '.mp4' and video.content_type != 'video/mp4') or (suffix == '.webm' and video.content_type != 'video/webm'):
            raise HTTPException(415, 'Invalid or mismatched video format')
        final_path = UPLOAD_DIR / (session_id + suffix)
        with connection() as con:
            con.execute('BEGIN IMMEDIATE')
            result = con.execute('UPDATE sessions SET status=?, video_path=?, video_bytes=?, updated_at=? WHERE id=? AND status=?',
                                 ('queued', str(final_path), size, utcnow(), session_id, 'created'))
            if result.rowcount != 1:
                raise HTTPException(409, 'Video already submitted')
            tmp_path.replace(final_path)
        return {'session_id': session_id, 'status': 'queued'}
    finally:
        await video.close()
        tmp_path.unlink(missing_ok=True)


@app.delete('/api/sessions/{session_id}')
def delete_session(session_id: str, token: str = Depends(require_token)):
    row = find_session(session_id, token)
    with connection() as con:
        con.execute('DELETE FROM sessions WHERE id=?', (session_id,))
    if row['video_path']:
        Path(row['video_path']).unlink(missing_ok=True)
    return {'deleted': True}


def process_one():
    """Claim one job; optionally run local pose landmarker when configured."""
    import json
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT id, video_path, video_bytes, lead_arm FROM sessions WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return False
        con.execute("UPDATE sessions SET status='processing', updated_at=? WHERE id=? AND status='queued'", (utcnow(), row['id']))
    sid, path = row['id'], Path(row['video_path'])
    try:
        if not path.is_file():
            raise RuntimeError('Video missing from storage')
        result = {
            'analysis_type': 'ingestion_only',
            'video_bytes': row['video_bytes'],
            'technique_analyzed': False,
            'message': 'Video received and processed. Boxing technique analysis will be added in Release 2.',
        }
        model_asset = os.environ.get('TOPTIGER_POSE_MODEL')
        if model_asset:
            from .pose_analysis import analyze_video
            result = analyze_video(path, Path(model_asset), row['lead_arm'])
            result['video_bytes'] = row['video_bytes']
        try:
            p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                duration = float(p.stdout.strip())
                if 0 < duration <= 180:
                    result['duration_seconds'] = round(duration, 2)
        except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
            pass
        with connection() as con:
            con.execute('UPDATE sessions SET status=?, result_json=?, updated_at=? WHERE id=? AND status=?',
                        ('completed', json.dumps(result), utcnow(), sid, 'processing'))
    except Exception as exc:
        with connection() as con:
            con.execute('UPDATE sessions SET status=?, result_json=?, updated_at=? WHERE id=? AND status=?',
                        ('failed', json.dumps({'message': str(exc)}), utcnow(), sid, 'processing'))
    return True
