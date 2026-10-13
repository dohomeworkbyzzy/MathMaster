"""Session-owned LAN ink channel. MathMaster's database/API remain loopback-only."""
import asyncio
import json
import math
import os
import queue
import secrets
import socket
import threading
import time
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


class Session:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.code = str(secrets.randbelow(900000) + 100000)
        self.queue = queue.Queue(maxsize=4096)
        self.closed = False
        self.attached = False
        self.connected = False
        self.created = time.monotonic()
        self.control = {'type': 'target', 'selected': False, 'reset': 0}

    def close(self):
        self.closed = True

    def emit(self, event):
        if not self.closed:
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                self.close()  # Never silently drop a pen-up.


def validate_event(event):
    kind = event.get('type')
    if kind == 'surface':
        ratio = event.get('ratio')
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not .2 <= ratio <= 5:
            raise ValueError('Invalid surface ratio')
        return {'type': kind, 'ratio': ratio}
    if kind == 'commit':
        return {'type': kind}
    if kind != 'contact' or type(event.get('down')) is not bool:
        raise ValueError('Invalid ink event')
    if not event['down']:
        return {'type': kind, 'down': False}
    x, y = event.get('x'), event.get('y')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
        raise ValueError('Invalid ink coordinates')
    return {'type': kind, 'down': True, 'id': 0, 'x': x, 'y': y}


class Bridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.server = None
        self.thread = None

    def start(self):
        with self.lock:
            if self.session and not self.session.closed:
                raise ValueError('另一页面正在使用手机书写，请先完成。')
            # Bind synchronously, so a busy port produces a visible error immediately.
            if not self.thread or not self.thread.is_alive():
                port = int(os.environ.get('MATHMASTER_PHONEPAD_PORT', '8766'))
                listener = socket.socket()
                try:
                    listener.bind(('0.0.0.0', port))
                    listener.listen(16)
                    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
                    app.websocket('/ink')(self.receive)
                    self.server = uvicorn.Server(uvicorn.Config(app, log_level='warning', ws='websockets',ws_max_size=1024,ws_max_queue=16))
                    self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [listener]}, daemon=True)
                    self.thread.start()
                except Exception:
                    listener.close()
                    raise ValueError(f'手机书写端口 {port} 无法启动，请检查端口占用。')
            session = self.session = Session()
            timer = threading.Timer(90, self.expire, args=(session,))
            timer.daemon = True
            timer.start()
            try:
                hosts = sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                                if not info[4][0].startswith(('127.', '169.254.', '198.18.', '198.19.'))},
                               key=lambda host: (not host.startswith('192.168.'), host))
            except OSError:
                hosts = []
            return {'token': session.token, 'code': session.code, 'hosts': hosts, 'port': int(os.environ.get('MATHMASTER_PHONEPAD_PORT','8766')),
                    'devices': [{'aspect_ratio': 2, 'x_range': [0, 1], 'y_range': [0, 1]}]}

    def expire(self, session):
        if not session.attached:
            session.close()

    def get(self, token):
        with self.lock:
            session = self.session
            if not session or session.closed or not secrets.compare_digest(token, session.token):
                raise ValueError('手机书写会话已结束，请重新开启。')
            return session

    def stop(self, token=None):
        with self.lock:
            if self.session:
                if token is not None and not secrets.compare_digest(token, self.session.token):
                    raise ValueError('无法关闭其他页面的书写会话。')
                self.session.close()
            if token is None and self.server:
                self.server.should_exit = True

    async def receive(self, ws: WebSocket):
        await ws.accept()
        session = None
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), 5))
            with self.lock:
                candidate = self.session
                if (not candidate or candidate.closed or not candidate.attached or candidate.connected
                        or hello.get('type') != 'hello' or not isinstance(hello.get('code'), str)
                        or not secrets.compare_digest(hello['code'], candidate.code)):
                    await ws.send_json({'type': 'error', 'message': '配对码不正确、页面未开启，或已有手机连接。'})
                    return
                candidate.connected = True
                session = candidate
            await ws.send_json({'type': 'ready'})
            session.emit({'type': 'status', 'message': '手机已连接'})
            last_control = None
            while not session.closed:
                if session.control != last_control:
                    last_control = dict(session.control)
                    await ws.send_json(last_control)
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), .1)
                except asyncio.TimeoutError:
                    continue
                if len(raw) > 1024:
                    raise ValueError('Ink message too large')
                session.emit(validate_event(json.loads(raw)))
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
            pass
        finally:
            if session:
                session.connected = False
                session.emit({'type': 'contact', 'down': False})
                session.emit({'type': 'commit'})
                session.emit({'type': 'status', 'message': '手机已断开，可重新连接'})
            try:
                await ws.close()
            except RuntimeError:
                pass

    async def events(self, session):
        with self.lock:
            duplicate = session.attached
            if not duplicate:session.attached = True
        if duplicate:
            yield 'data: ' + json.dumps({'type': 'error', 'message': '会话已被连接'}) + '\n\n'
            return
        try:
            while not session.closed and time.monotonic() - session.created < 1800:
                for _ in range(128):
                    try:
                        event = session.queue.get_nowait()
                    except queue.Empty:
                        break
                    yield 'data: ' + json.dumps(event) + '\n\n'
                yield ': keepalive\n\n'
                await asyncio.sleep(.008)
        finally:
            session.close()


bridge = Bridge()
