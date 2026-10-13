"""Self-contained Windows launcher and isolated worker dispatch."""
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import runpy
import socket
import sys
import threading
import time
import urllib.request


def dispatch():
    workers = {
        '--math-worker': 'backend.worker',
        '--import-worker': 'backend.importer',
        '--touchpad-worker': 'backend.touchpad_native',
    }
    if len(sys.argv) > 1 and sys.argv[1] in workers:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream and hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
        runpy.run_module(workers[sys.argv[1]], run_name='__main__')
        return True
    return False


def main():
    if os.name != 'nt':
        raise RuntimeError('This launcher is for Windows only.')
    # Set this before importing any application module that opens SQLite.
    data = Path(os.environ.get('MATHMASTER_DATA', Path(os.environ['LOCALAPPDATA']) / 'MathMaster' / 'data')).resolve()
    os.environ['MATHMASTER_DATA'] = str(data)
    os.environ['PYTHONUTF8'] = '1'
    instance = hashlib.sha256(str(data).lower().encode()).hexdigest()[:24]
    state = data.parent / ('runtime-' + instance + '.json')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    event_name = 'Local\\MathMasterStop-' + instance
    if '--quit' in sys.argv:
        event = kernel.OpenEventW(0x0002, False, event_name)
        if event:
            try:
                kernel.SetEvent(event)
            finally:
                kernel.CloseHandle(event)
        return
    mutex = kernel.CreateMutexW(None, True, 'Local\\MathMasterRun-' + instance)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    already_running = ctypes.get_last_error() == 183
    from scripts.bootstrap import open_browser
    if already_running:
        try:
            for _ in range(80):
                if state.exists():
                    info = json.loads(state.read_text(encoding='utf-8'))
                    try:
                        with urllib.request.urlopen(info['url'] + '/api/health', timeout=.5) as r:
                            if json.load(r).get('local'):
                                if '--no-browser' not in sys.argv:
                                    open_browser(info['url'])
                                return
                    except (OSError, ValueError):
                        pass
                time.sleep(.2)
            raise RuntimeError('已有实例正在启动，请稍后重试。')
        finally:
            kernel.CloseHandle(mutex)
    stop_event = kernel.CreateEventW(None, True, False, event_name)
    server = None
    server_thread = None
    tray = None
    try:
        if not stop_event:
            raise ctypes.WinError(ctypes.get_last_error())
        data.mkdir(parents=True, exist_ok=True)
        logs = data.parent / 'logs'
        logs.mkdir(exist_ok=True)
        log = (logs / 'mathmaster.log').open('a', encoding='utf-8', buffering=1)
        sys.stdout = log
        sys.stderr = log
        from logging.handlers import RotatingFileHandler
        logging.basicConfig(handlers=[RotatingFileHandler(logs/'launcher.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')], level=logging.INFO)
        preferred = int(os.environ.get('MATHMASTER_PORT', '8765'))
        for port in range(preferred, min(preferred + 10, 65536)):
            if port==int(os.environ.get('MATHMASTER_PHONEPAD_PORT','8766')):
                continue  # Reserve the independent phone ink channel.
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                    break
                except OSError:
                    continue
        else:
            raise RuntimeError('本地端口已被占用，请关闭其他实例后再启动。')
        url = f'http://127.0.0.1:{port}'
        os.environ['MATHMASTER_ALLOWED_ORIGINS'] = url + f',http://localhost:{port}'
        import uvicorn
        from backend.app import app
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None))
        server_thread = threading.Thread(target=server.run, name='MathMaster API', daemon=True)
        server_thread.start()
        for _ in range(300):
            if server.started:
                break
            if not server_thread.is_alive():
                raise RuntimeError('本地服务启动失败，请查看日志。')
            time.sleep(.1)
        else:
            raise RuntimeError('本地服务启动超时，请查看日志。')
        state.write_text(json.dumps({'url': url, 'pid': os.getpid(), 'data_directory': str(data)}), encoding='utf-8')
        if '--no-browser' not in sys.argv:
            open_browser(url)

        def shutdown():
            server.should_exit = True
            if tray:
                tray.stop()

        def monitor():
            while server_thread.is_alive():
                if kernel.WaitForSingleObject(stop_event, 250) == 0:
                    break
            shutdown()

        threading.Thread(target=monitor, daemon=True).start()
        if '--headless' in sys.argv:
            server_thread.join()
        else:
            import pystray
            from PIL import Image
            bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
            tray = pystray.Icon('MathMaster', Image.open(bundle/'packaging/windows/mathmaster.ico'), 'MathMaster', pystray.Menu(
                pystray.MenuItem('打开 MathMaster', lambda: open_browser(url), default=True),
                pystray.MenuItem('打开数据文件夹', lambda: os.startfile(data)),
                pystray.MenuItem('退出 MathMaster', lambda: shutdown()),
            ))
            def tray_ready(icon):
                icon.visible = True
                if server.should_exit:
                    icon.stop()
            tray.run(setup=tray_ready)
    finally:
        if server:
            server.should_exit = True
        if server_thread:
            server_thread.join(timeout=10)
        if state.exists() and not (server_thread and server_thread.is_alive()):
            state.unlink(missing_ok=True)
        if stop_event:
            kernel.CloseHandle(stop_event)
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    if not dispatch():
        try:
            main()
        except Exception as error:
            logging.exception('MathMaster startup failed')
            if '--headless' not in sys.argv and os.name == 'nt':
                ctypes.windll.user32.MessageBoxW(None, str(error) + '\n日志位于本地 MathMaster 数据目录的 logs 文件夹。', 'MathMaster 启动失败', 0x10)
            raise SystemExit(1)
