import asyncio
import queue
import sys
from fastapi.testclient import TestClient
from backend.app import app
from backend.touchpad import Bridge


def test_local_bridge_rejects_foreign_origins_and_unowned_streams():
    client = TestClient(app)
    assert client.post('/api/touchpad/start', headers={'Origin': 'https://other.example'}).status_code == 403
    assert client.get('/api/touchpad/events?token=not-the-owner').status_code == 403
    assert client.post('/api/touchpad/stop', json={'token': 'short'}).status_code == 422
    assert client.post('/api/window',json={'mode':'compact'},headers={'Origin':'https://other.example'}).status_code==403
    assert client.post('/api/window',json={'mode':'unknown'}).status_code==422
    if sys.platform != 'win32':
        result = client.get('/api/touchpad/status').json()
        assert not result['available'] and result['devices'] == []
        assert client.post('/api/touchpad/start').status_code == 422
        assert client.post('/api/window',json={'mode':'compact'}).status_code==422


def test_stream_disconnect_closes_session_without_letting_duplicate_close_owner():
    class Session:
        attached = False
        closed = False
        created = __import__('time').monotonic()
        queue = queue.Queue()
        def close(self):
            self.closed = True
    async def check():
        bridge = Bridge()
        session = Session()
        session.queue.put({'type': 'contact', 'down': True, 'x': .25, 'y': .75})
        first = bridge.events(session)
        assert '"x": 0.25' in await anext(first)
        duplicate = bridge.events(session)
        assert 'error' in await anext(duplicate)
        await duplicate.aclose()
        assert not session.closed
        await first.aclose()
        assert session.closed
    asyncio.run(check())
