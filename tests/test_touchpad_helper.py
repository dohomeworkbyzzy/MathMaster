import http.client
import json
import threading
from backend.touchpad_helper import HelperServer


class FakeBridge:
    def __init__(self):
        self.starts = 0
        self.closed = False

    def start(self):
        self.starts += 1
        return {'token': 'a'*32, 'devices': [{'x_range': [0, 100], 'y_range': [0, 60]}]}

    def get(self, token):
        if token != 'a'*32:
            raise ValueError('Invalid token')
        return self

    def stop(self, token=None):
        if token is not None:
            self.get(token)
        self.closed = True

    async def events(self, session):
        try:
            yield 'data: {"type":"contact","x":0.25,"y":0.5}\n\n'
        finally:
            self.closed = True


def test_helper_pairs_local_device_binds_origin_and_streams_without_server():
    bridge = FakeBridge()
    server = HelperServer(('127.0.0.1', 0), bridge, '12345678')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None, origin='https://math.example', extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        headers = {'Origin': origin, 'Content-Type': 'application/json', **(extra or {})}
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        status, result, response_headers = response.status, response.read(), response.headers
        connection.close()
        return status, result, response_headers

    try:
        status, html, _ = call('GET', '/connect', origin='')
        assert status == 200 and b'window.opener.postMessage' in html
        status, _, headers = call('OPTIONS', '/api/touchpad/start')
        assert status == 204
        assert headers['Access-Control-Allow-Origin'] == 'https://math.example'
        assert headers['Access-Control-Allow-Private-Network'] == 'true'
        assert call('POST', '/api/touchpad/start', {'code': 'wrong'})[0] == 403
        assert call('POST', '/api/touchpad/start', {'code': '12345678'}, extra={'Host': 'evil.example'})[0] == 403
        assert call('POST', '/api/touchpad/start', {'code': '12345678'}, origin='null')[0] == 403
        assert call('POST', '/api/touchpad/start', {'code': '12345678'}, extra={'X-Forwarded-For': '127.0.0.1'})[0] == 403
        assert bridge.starts == 0
        assert call('POST', '/api/touchpad/start', {'code': '12345678'})[0] == 200
        assert bridge.starts == 1
        assert call('GET', '/api/touchpad/events?token='+'a'*32, origin='https://other.example')[0] == 403
        assert call('POST', '/api/touchpad/stop', {'token': 'wrong'})[0] == 403
        assert not bridge.closed
        status, data, _ = call('GET', '/api/touchpad/events?token='+'a'*32)
        assert status == 200 and b'"x":0.25' in data and bridge.closed
        assert call('POST', '/api/touchpad/stop', {'token': 'a'*32})[0] == 200
        local_headers = {'Sec-Fetch-Site': 'same-origin'}
        assert call('POST', '/api/touchpad/start', {'code': '12345678'}, origin='', extra=local_headers)[0] == 200
        assert call('GET', '/api/touchpad/events?token='+'a'*32, origin='', extra=local_headers)[0] == 200
        for _ in range(9):
            assert call('POST', '/api/touchpad/start', {'code': 'bad'})[0] == 403
        assert call('POST', '/api/touchpad/start', {'code': '12345678'})[0] == 429
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
