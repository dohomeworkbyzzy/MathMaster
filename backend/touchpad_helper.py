"""Visitor-owned loopback input bridge. No database or application server required."""
import asyncio
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .touchpad import Bridge
from .touchpad_connect import HTML

PORT = 18765


class HelperServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address=('127.0.0.1', PORT), bridge=None, code=None):
        super().__init__(address, Handler)
        self.bridge = bridge or Bridge()
        self.code = code or f'{secrets.randbelow(100_000_000):08d}'
        self.owner = None
        self.guard = threading.RLock()
        self.failures = deque()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass  # Session tokens must not enter request logs.

    def origin(self):
        origin = self.headers.get('Origin', '')
        if not origin and self.headers.get('Sec-Fetch-Site') == 'same-origin':
            origin = f'http://127.0.0.1:{self.server.server_port}'
        try:
            parsed = urlsplit(origin)
            if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment:
                return origin
        except ValueError:
            pass
        return None

    def allowed(self):
        # Reject DNS rebinding and proxy requests even when the TCP peer is local.
        return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                and self.client_address[0] == '127.0.0.1'
                and not any(k.lower() == 'forwarded' or k.lower().startswith('x-forwarded-') for k in self.headers)
                and self.origin())

    def send_headers(self, status, content_type='application/json', length=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Vary', 'Origin')
        if self.allowed():
            self.send_header('Access-Control-Allow-Origin', self.origin())
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_headers(status, length=len(body))
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self.allowed():
            return self.reply(403, {'detail': '只允许本机网页连接。'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.origin())
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        if not self.allowed():
            return self.reply(403, {'detail': '只允许本机网页连接。'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('无效请求')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('无效请求')
        except (ValueError, OSError):
            self.close_connection = True
            return self.reply(400, {'detail': '无效请求'})
        with self.server.guard:
            if self.path == '/api/touchpad/start':
                now = time.monotonic()
                while self.server.failures and now - self.server.failures[0] > 60:
                    self.server.failures.popleft()
                if len(self.server.failures) >= 10:
                    return self.reply(429, {'detail': '配对尝试过多，请一分钟后重试。'})
                code = body.get('code', '')
                if not isinstance(code, str) or not code.isascii() or not secrets.compare_digest(code, self.server.code):
                    self.server.failures.append(now)
                    return self.reply(403, {'detail': '配对码不正确，请查看本地助手窗口。'})
                try:
                    session = self.server.bridge.start()
                except Exception as e:
                    return self.reply(422, {'detail': str(e)})
                self.server.owner = self.origin()
                return self.reply(200, session)
            if self.path == '/api/touchpad/stop':
                try:
                    self.owned(body.get('token'))
                    self.server.bridge.stop(body['token'])
                except ValueError as e:
                    return self.reply(403, {'detail': str(e)})
                return self.reply(200, {'stopped': True})
        self.reply(404, {'detail': 'Not found'})

    def owned(self, token):
        if self.origin() != self.server.owner or not isinstance(token, str) or not token.isascii() or len(token) < 20:
            raise ValueError('书写会话不属于当前网页。')
        return self.server.bridge.get(token)

    def do_GET(self):
        if (self.path.split('?', 1)[0] == '/connect'
                and self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                and self.client_address[0] == '127.0.0.1'):
            body = HTML.encode()
            self.send_headers(200, 'text/html; charset=utf-8', len(body))
            self.wfile.write(body)
            return
        if not self.allowed():
            return self.reply(403, {'detail': '只允许本机网页连接。'})
        url = urlsplit(self.path)
        if url.path != '/api/touchpad/events':
            return self.reply(404, {'detail': 'Not found'})
        try:
            with self.server.guard:
                session = self.owned(parse_qs(url.query).get('token', [''])[0])
        except ValueError as e:
            return self.reply(403, {'detail': str(e)})
        self.close_connection = True
        self.send_headers(200, 'text/event-stream')

        async def stream():
            events = self.server.bridge.events(session)
            try:
                async for item in events:
                    self.wfile.write(item.encode())
                    self.wfile.flush()
            finally:
                await events.aclose()
        try:
            asyncio.run(stream())
        except (OSError, ConnectionError):
            pass


def main():
    try:
        server = HelperServer()
    except OSError:
        print('本地助手端口已被占用，请先关闭已有助手。', flush=True)
        return
    print(f'MathMaster Touchpad\n仅接收本机网页连接：http://127.0.0.1:{server.server_port}\n配对码：{server.code}\n在网页点击“触控板书写”，输入上面的配对码。\n保持此窗口开启；按 Ctrl+C 退出。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.bridge.stop()
        server.server_close()


if __name__ == '__main__':
    main()
