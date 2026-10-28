import math
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.phonepad import Bridge, Session, validate_event
from backend.app import app


def test_phonepad_does_not_expose_local_api_or_accept_unowned_sessions():
    client = TestClient(app)
    assert client.post('/api/phonepad/start', headers={'Origin': 'https://other.example'}).status_code == 403
    assert client.get('/api/phonepad/events?token=not-owner').status_code == 403
    assert client.post('/api/phonepad/control', json={'token': 'x' * 32, 'reset': True}).status_code == 403
    assert client.post('/api/phonepad/stop', json={'token': 'short'}).status_code == 422


def test_phonepad_rejects_invalid_geometry():
    for event in [{'type': 'contact', 'down': True, 'x': math.nan, 'y': 0},
                  {'type': 'contact', 'down': True, 'x': 2, 'y': 0},
                  {'type': 'surface', 'ratio': 0}, {'type': 'surface', 'ratio': True},
                  {'type': 'keyboard', 'key': 7}]:
        with pytest.raises(ValueError):validate_event(event)
    assert validate_event({'type': 'contact', 'down': True, 'x': 0, 'y': 1})['y'] == 1


def test_pairing_absolute_ink_and_disconnect_commit():
    bridge = Bridge()
    session = bridge.session = Session()
    session.attached = True
    sidecar = FastAPI()
    sidecar.websocket('/ink')(bridge.receive)
    with TestClient(sidecar) as client:
        assert client.get('/api/questions').status_code == 404
        with client.websocket_connect('/ink') as ws:
            ws.send_json({'type': 'hello', 'code': 'wrong'})
            assert ws.receive_json()['type'] == 'error'
        with client.websocket_connect('/ink') as ws:
            ws.send_json({'type': 'hello', 'code': session.code})
            assert ws.receive_json()['type'] == 'ready'
            assert ws.receive_json()['type'] == 'target'
            ws.send_json({'type': 'surface', 'ratio': 2.5})
            ws.send_json({'type': 'contact', 'down': True, 'x': .1, 'y': .9})
            ws.send_json({'type': 'contact', 'down': False})
        events = []
        while not session.queue.empty():events.append(session.queue.get_nowait())
        assert {'type': 'surface', 'ratio': 2.5} in events
        assert {'type': 'contact', 'down': True, 'id': 0, 'x': .1, 'y': .9} in events
        assert events[-2]['type'] == 'commit'
        assert not session.connected


def test_phone_session_survives_long_runtime_and_event_stream_reconnect():
    async def exercise():
        bridge = Bridge()
        session = bridge.session = Session()
        session.created -= 3600
        session.connected = True
        session.control['selected'] = True
        stream = bridge.events(session)
        assert 'status' in await anext(stream)
        assert 'keepalive' in await anext(stream)
        await stream.aclose()
        assert not session.closed and not session.attached
        assert session.connected and not session.control['selected']
        assert bridge.get(session.token) is session
        resumed = bridge.events(session)
        assert 'status' in await anext(resumed)
        assert session.attached
        await resumed.aclose()
        bridge.stop(session.token)
        assert session.closed
    asyncio.run(exercise())
