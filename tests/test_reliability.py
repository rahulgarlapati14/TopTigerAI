import time
from app.main import app, claim_job, finalize_job, MAX_ATTEMPTS
from app.db import connection
from fastapi.testclient import TestClient

client = TestClient(app)


def queued_session():
    s = client.post('/api/sessions', json={'station_id': 'demo-station', 'consent': True}).json()
    sid = s['session_id']
    r = client.post(f'/api/sessions/{sid}/video', headers={'X-Session-Token': s['session_token']},
                    files={'video': ('a.mp4', b'\x00\x00\x00\x18ftypisom' + b'0'*40, 'video/mp4')})
    assert r.status_code == 202
    return sid


def test_expired_lease_can_be_reclaimed_but_stale_owner_cannot_finalize():
    sid = queued_session()
    a = claim_job('worker-a')
    assert a['id'] == sid
    with connection() as db:
        db.execute('UPDATE sessions SET lease_until=? WHERE id=?', (int(time.time()) - 1, sid))
    b = claim_job('worker-b')
    assert b['id'] == sid
    assert b['attempt_count'] == 2
    assert finalize_job(sid, 'worker-a', {'message': 'stale'}) is None
    assert finalize_job(sid, 'worker-b', {'message': 'ok'}) == 'completed'
    with connection() as db:
        record = db.execute('SELECT status, result_json FROM sessions WHERE id=?', (sid,)).fetchone()
    assert record['status'] == 'completed'
    assert 'stale' not in record['result_json']


def test_retry_then_dead_letter_terminal_failure():
    sid = queued_session()
    for n in range(1, MAX_ATTEMPTS+1):
        with connection() as db:
            db.execute('UPDATE sessions SET next_attempt_at=0 WHERE id=?', (sid,))
        worker = f'retry-{n}'
        row = claim_job(worker)
        assert row['id'] == sid
        result = finalize_job(sid, worker, {'message': 'failed'}, error='transient')
        assert result == ('failed' if n == MAX_ATTEMPTS else 'queued')
    assert claim_job('extra') is None


def test_metrics_do_not_expose_session_tokens():
    s = client.post('/api/sessions', json={'station_id': 'demo-station', 'consent': True}).json()
    r = client.get('/metrics')
    assert r.status_code == 200
    assert 'toptiger_sessions' in r.text
    assert s['session_token'] not in r.text
