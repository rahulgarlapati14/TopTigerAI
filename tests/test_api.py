import os
import tempfile
from pathlib import Path

_TEST_DIR = tempfile.TemporaryDirectory()
os.environ['TOPTIGER_DATA_DIR'] = _TEST_DIR.name

from fastapi.testclient import TestClient
from app.main import app, process_one

client = TestClient(app)


def start():
    res = client.post('/api/sessions', json={'station_id':'demo-station','consent':True})
    assert res.status_code == 201
    return res.json()


def auth(session):
    return {'X-Session-Token': session['session_token']}


def test_consent_required():
    assert client.post('/api/sessions', json={'station_id':'demo-station','consent':False}).status_code == 422


def test_unknown_station_rejected():
    assert client.post('/api/sessions', json={'station_id':'unknown','consent':True}).status_code == 404


def test_access_token_required():
    session = start()
    assert client.get('/api/sessions/'+session['session_id']).status_code == 401
    assert client.get('/api/sessions/'+session['session_id'],headers={'X-Session-Token':'incorrect'}).status_code == 404


def test_upload_queue_process_delete():
    session = start()
    path = '/api/sessions/'+session['session_id']
    video = b'\x00\x00\x00\x18ftypisom'+b'0'*32
    response = client.post(path+'/video',headers=auth(session),files={'video':('clip.mp4',video,'video/mp4')})
    assert response.status_code == 202, response.text
    assert response.json()['status'] == 'queued'
    assert client.post(path+'/video',headers=auth(session),files={'video':('clip.mp4',video,'video/mp4')}).status_code == 409
    assert process_one() is True
    status = client.get(path,headers=auth(session)).json()
    assert status['status']=='completed'
    assert status['result']['technique_analyzed'] is False
    assert client.delete(path,headers=auth(session)).status_code == 200
    assert client.get(path,headers=auth(session)).status_code == 404


def test_invalid_format_rejected_and_retry_allowed():
    session = start()
    path='/api/sessions/'+session['session_id']+'/video'
    result=client.post(path,headers=auth(session),files={'video':('fake.mp4',b'not a video','video/mp4')})
    assert result.status_code == 415
    assert client.get('/api/sessions/'+session['session_id'],headers=auth(session)).json()['status']=='created'


def test_oversize_rejected():
    session=start()
    path='/api/sessions/'+session['session_id']+'/video'
    result=client.post(path,headers=auth(session),files={'video':('clip.mp4',b'\x00\x00\x00\x18ftypisom'+b'x'*(25*1024*1024),'video/mp4')})
    assert result.status_code == 413
