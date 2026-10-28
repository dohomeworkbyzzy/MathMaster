"""Bounded, session-owned local bridge to the isolated native touchpad reader."""
import asyncio
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import ctypes as c
from .runtime import ROOT, worker_command


class ClipRect(c.Structure):
    _fields_ = [('left', c.c_int32), ('top', c.c_int32), ('right', c.c_int32), ('bottom', c.c_int32)]


def clip_snapshot():
    if os.name != 'nt':return None
    rect = ClipRect()
    if c.windll.user32.GetClipCursor(c.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def status():
    if os.name != 'nt':
        return {'available': False, 'devices': [], 'external_mice': 0,
                'message': '原始触控板书写需要使用 Windows 的 start.bat 启动。'}
    try:
        p = subprocess.run(worker_command('backend.touchpad_native', '--probe'),
                           cwd=ROOT, capture_output=True, timeout=4,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(p.stdout)
    except Exception as e:
        return {'available': False, 'devices': [], 'external_mice': 0,
                'message': '读取触控板失败：' + str(e)}


class Session:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.queue = queue.Queue(maxsize=4096)
        self.closed = False
        self.attached = False
        self.created = time.monotonic()
        self.window_handle = None
        self.original_clip = clip_snapshot()
        self.process = subprocess.Popen(worker_command('backend.touchpad_native'),
                                        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in self.process.stdout:
                if self.closed:
                    break
                if len(line) > 65536:
                    break
                self.queue.put_nowait(json.loads(line))
        except (ValueError, queue.Full):
            self.close()
        finally:
            self.process.stdout.close()
            if not self.closed:
                try:
                    self.queue.put_nowait({'type': 'error', 'message': '触控板读取进程已退出，请重新开启。'})
                except queue.Full:
                    self.close()

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            if self.window_handle and os.name == 'nt':
                post = c.windll.user32.PostMessageW
                post.argtypes = [c.c_void_p, c.c_uint32, c.c_size_t, c.c_ssize_t]
                post(self.window_handle, 0x0010, 0, 0)  # WM_CLOSE releases the cursor first.
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=1)
        if os.name == 'nt' and self.original_clip:
            current = clip_snapshot()
            if current and current[2]-current[0] <= 1 and current[3]-current[1] <= 1 and current != self.original_clip:
                # A crashed worker must not leave the desktop cursor confined.
                c.windll.user32.ClipCursor(c.byref(ClipRect(*self.original_clip)))


class Bridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None

    def start(self):
        with self.lock:
            if self.session and not self.session.closed:
                raise ValueError('另一页面正在使用触控板，请先关闭该页面的书写模式。')
            if os.name != 'nt':
                raise ValueError(status()['message'])
            session = Session()
            try:
                ready = session.queue.get(timeout=4)
                if ready.get('type') != 'ready' or not ready.get('available'):
                    raise ValueError(ready.get('message') or '触控板读取器未能启动。')
                session.window_handle = ready.get('window_handle')
                if ready.get('external_mice', 0) < 1:
                    raise ValueError('请先连接外接鼠标，用于选择落笔位置和收笔。')
            except Exception:
                session.close()
                raise
            self.session = session
            # A start request without an SSE subscriber must not leave a capture process alive.
            expiry = threading.Timer(5, self.expire_unattached, args=(session,))
            expiry.daemon = True
            expiry.start()
            return {'token': session.token, **ready}

    def expire_unattached(self, session):
        with self.lock:
            if not session.attached:
                session.close()

    def get(self, token):
        with self.lock:
            session = self.session
            if not session or session.closed or not secrets.compare_digest(token, session.token):
                raise ValueError('书写会话已结束，请重新开启。')
            return session

    def stop(self, token=None):
        with self.lock:
            if self.session:
                if token is not None and not secrets.compare_digest(token, self.session.token):
                    raise ValueError('无法关闭其他页面的书写会话。')
                self.session.close()

    async def events(self, session):
        with self.lock:
            duplicate = session.attached
            if not duplicate:
                session.attached = True
        if duplicate:
            yield 'data: ' + json.dumps({'type': 'error', 'message': '该书写会话已被连接。'}) + '\n\n'
            return
        try:
            while not session.closed and time.monotonic() - session.created < 1800:
                batch = []
                while len(batch) < 128:
                    try:
                        batch.append(session.queue.get_nowait())
                    except queue.Empty:
                        break
                if batch:
                    for item in batch:
                        yield 'data: ' + json.dumps(item) + '\n\n'
                        if item.get('type') == 'error':
                            return
                else:
                    yield ': keepalive\n\n'
                await asyncio.sleep(.008)
            yield 'data: ' + json.dumps({'type': 'error', 'message': '书写会话已结束，请重新开启。'}) + '\n\n'
        finally:
            session.close()


bridge = Bridge()
