"""TopTigerAI: local demo API. Not production-ready for real gyms."""
import os
import secrets
import subprocess
from datetime import datetime, timezone
import time
import json
import threading
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, Header, Depends
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from .db import connection, columns, UPLOAD_DIR, IS_POSTGRES
from .telemetry import SESSION_COUNTS, JOBS_CLAIMED, JOBS_SUCCEEDED, JOBS_RETRIED, JOBS_FAILED, PROCESSING_SECONDS

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
STATION_ID = os.environ.get('TOPTIGER_STATION_ID', 'demo-station')

app = FastAPI(title='TopTigerAI', version='0.1.0')
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')


def utcnow():
    return datetime.now(timezone.utc).isoformat()


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
            lead_arm TEXT NOT NULL DEFAULT 'left',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at BIGINT NOT NULL DEFAULT 0,
            lease_until BIGINT NOT NULL DEFAULT 0,
            worker_id TEXT
        )''')
        existing = columns(con, 'sessions')
        additions = {
            'lead_arm': "TEXT NOT NULL DEFAULT 'left'",
            'attempt_count': 'INTEGER NOT NULL DEFAULT 0',
            'next_attempt_at': 'BIGINT NOT NULL DEFAULT 0',
            'lease_until': 'BIGINT NOT NULL DEFAULT 0',
            'worker_id': 'TEXT',
        }
        for name, ddl in additions.items():
            if name not in existing:
                con.execute(f'ALTER TABLE sessions ADD COLUMN {name} {ddl}')


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


@app.get('/metrics')
def metrics():
    with connection() as con:
        counts = {r['status']: r['n'] for r in con.execute('SELECT status, COUNT(*) AS n FROM sessions GROUP BY status').fetchall()}
    for state in ('created', 'queued', 'processing', 'completed', 'failed'):
        SESSION_COUNTS.labels(state=state).set(counts.get(state, 0))
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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


MAX_ATTEMPTS = 3
LEASE_SECONDS = 300


def claim_job(worker_id: str, now: int | None = None):
    """Atomic lease claim with PostgreSQL SKIP LOCKED or SQLite serialization."""
    now = int(time.time()) if now is None else now
    eligibility = "((status='queued' AND next_attempt_at<=?) OR (status='processing' AND lease_until<=?)) AND attempt_count < ?"
    with connection() as con:
        if IS_POSTGRES:
            sql = f"""WITH available AS (
                SELECT id FROM sessions WHERE {eligibility}
                ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
            ) UPDATE sessions AS s SET status='processing', worker_id=?,
                attempt_count=s.attempt_count+1, lease_until=?, updated_at=?
                FROM available WHERE s.id=available.id RETURNING s.*"""
            row = con.execute(sql, (now, now, MAX_ATTEMPTS, worker_id, now + LEASE_SECONDS, utcnow())).fetchone()
        else:
            con.execute('BEGIN IMMEDIATE')
            sql = f"""UPDATE sessions SET status='processing', worker_id=?,
                attempt_count=attempt_count+1, lease_until=?, updated_at=?
                WHERE id=(SELECT id FROM sessions WHERE {eligibility} ORDER BY created_at LIMIT 1)
                RETURNING *"""
            row = con.execute(sql, (worker_id, now + LEASE_SECONDS, utcnow(), now, now, MAX_ATTEMPTS)).fetchone()
    if row:
        JOBS_CLAIMED.inc()
    return dict(row) if row else None


def heartbeat(session_id: str, worker_id: str, stop: threading.Event):
    """Keep lease alive while the model is doing inference."""
    while not stop.wait(30):
        try:
            with connection() as con:
                row = con.execute("""UPDATE sessions SET lease_until=?
                    WHERE id=? AND worker_id=? AND status='processing'""",
                    (int(time.time()) + LEASE_SECONDS, session_id, worker_id))
                if row.rowcount != 1:
                    return
        except Exception:
            return


def finalize_job(session_id: str, worker_id: str, result: dict, error: str | None = None):
    """Only the current lease owner may finish, retry, or fail a job."""
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT attempt_count FROM sessions WHERE id=? AND worker_id=? AND status='processing'",
                          (session_id, worker_id)).fetchone()
        if not row:
            return None
        if error is None:
            state, delay = 'completed', 0
        elif row['attempt_count'] >= MAX_ATTEMPTS:
            state, delay = 'failed', 0
        else:
            state, delay = 'queued', min(60, 2 ** row['attempt_count'])
        con.execute("""UPDATE sessions SET status=?, result_json=?, worker_id=NULL,
            lease_until=0, next_attempt_at=?, updated_at=?
            WHERE id=? AND worker_id=? AND status='processing'""",
            (state, json.dumps(result), int(time.time()) + delay, utcnow(), session_id, worker_id))
    if state == 'completed':
        JOBS_SUCCEEDED.inc()
    elif state == 'queued':
        JOBS_RETRIED.inc()
    else:
        JOBS_FAILED.inc()
    return state


def analyze_claim(row):
    path = Path(row['video_path'])
    if not path.is_file():
        raise RuntimeError('Video missing from storage')
    result = {
        'analysis_type': 'ingestion_only',
        'video_bytes': row['video_bytes'],
        'technique_analyzed': False,
        'message': 'Video received and processed. Pose analysis requires a configured model asset.',
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
    # Feedback is optional. The gateway sees only bounded structured observations,
    # never the uploaded video or a member's identity.
    gateway_url = os.environ.get('TOPTIGER_GATEWAY_URL')
    gateway_key = os.environ.get('TOPTIGER_GATEWAY_KEY')
    if gateway_url and gateway_key and result.get('analysis_type') == 'experimental_pose_extension_v1':
        try:
            import httpx
            payload = {
                'observations': {
                    'lead_arm': row['lead_arm'],
                    'extension_cycle_candidates': result.get('extension_cycle_candidates'),
                    'usable_frame_fraction': result['usable_frame_fraction'],
                    'duration_seconds': result['duration_seconds'],
                    'technique_analyzed': False,
                }
            }
            with httpx.Client(timeout=12) as client:
                response = client.post(
                    gateway_url.rstrip('/') + '/v1/feedback',
                    headers={'Authorization': 'Bearer ' + gateway_key},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            result['experimental_feedback'] = data['feedback']
            result['feedback_backend'] = data['backend']
            result['feedback_status'] = 'generated_unreviewed'
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            result['feedback_status'] = 'unavailable'
    return result


def process_one():
    worker_id = secrets.token_hex(16)
    row = claim_job(worker_id)
    if row is None:
        return False
    stop = threading.Event()
    monitor = threading.Thread(target=heartbeat, args=(row['id'], worker_id, stop), daemon=True)
    monitor.start()
    start = time.monotonic()
    try:
        result = analyze_claim(row)
        finalize_job(row['id'], worker_id, result)
    except Exception:
        # Avoid exposing filesystem paths or exception text to gym members.
        finalize_job(row['id'], worker_id,
                     {'message': 'Processing failed. Retry scheduled or limit reached.'}, 'processing error')
    finally:
        stop.set()
        monitor.join(timeout=1)
        PROCESSING_SECONDS.observe(time.monotonic() - start)
    return True
