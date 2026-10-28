"""Portable Windows server. All state is relative to the executable directory."""
import argparse
import ctypes
import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
from urllib.parse import urlsplit


DEFAULT={'host':'0.0.0.0','port':8509,'public_origins':['http://39.129.11.4:8509'],'background_indexing':True}


def validate_origin(value):
    url=urlsplit(value.strip().rstrip('/'))
    if (url.scheme not in ('http','https') or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment):raise ValueError('Use an HTTP(S) origin without a path.')
    url.port  # Validate the port, if present.
    return url.geturl()


def settings(root):
    path=root/'config.json'
    value={**DEFAULT,**(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {})}
    if type(value['port']) is not int or not 1<=value['port']<=65535:raise ValueError('Invalid listening port.')
    if value['host']!='localhost':ipaddress.ip_address(value['host'])
    if not isinstance(value['public_origins'],list):raise ValueError('public_origins must be a list.')
    value['public_origins']=[validate_origin(origin) for origin in value['public_origins']]
    if type(value['background_indexing']) is not bool:raise ValueError('background_indexing must be true or false.')
    return value


class WindowsInstance:
    def __init__(self,root):
        key=hashlib.sha256(str(root).lower().encode()).hexdigest()[:24]
        self.event_name='Local\\master-stop-'+key
        self.mutex_name='Local\\master-run-'+key
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,args,result in [
            ('CreateMutexW',[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p],ctypes.c_void_p),
            ('CreateEventW',[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_wchar_p],ctypes.c_void_p),
            ('OpenEventW',[ctypes.c_uint32,ctypes.c_int,ctypes.c_wchar_p],ctypes.c_void_p),
            ('SetEvent',[ctypes.c_void_p],ctypes.c_int),
            ('WaitForSingleObject',[ctypes.c_void_p,ctypes.c_uint32],ctypes.c_uint32),
            ('CloseHandle',[ctypes.c_void_p],ctypes.c_int)]:
            function=getattr(self.kernel,name);function.argtypes=args;function.restype=result
        self.mutex=None;self.event=None

    def stop(self):
        event=self.kernel.OpenEventW(0x0002,False,self.event_name)
        if event:
            try:
                if not self.kernel.SetEvent(event):raise ctypes.WinError(ctypes.get_last_error())
            finally:self.kernel.CloseHandle(event)
        print('Stop requested.' if event else 'No running instance.')

    def acquire(self):
        self.mutex=self.kernel.CreateMutexW(None,False,self.mutex_name)
        if not self.mutex:raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:return False
        self.event=self.kernel.CreateEventW(None,True,False,self.event_name)
        if not self.event:raise ctypes.WinError(ctypes.get_last_error())
        return True

    def close(self):
        for handle in (self.event,self.mutex):
            if handle:self.kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser(prog='master')
    parser.add_argument('--root',type=Path)
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--configure',action='store_true')
    parser.add_argument('--url')
    args=parser.parse_args()
    root=(args.root or (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])).resolve()
    root.mkdir(parents=True,exist_ok=True)
    instance=None
    try:
        if args.stop:
            instance=WindowsInstance(root);instance.stop();return 0
        config=settings(root)
        if args.configure:
            value=args.url or input('Public URL (example http://39.129.11.4:8509): ').strip()
            origin=validate_origin(value if '://' in value else 'http://'+value)
            config['public_origins']=[origin]
            url=urlsplit(origin)
            if url.port is not None:config['port']=url.port
            (root/'config.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
            print('Configuration saved. Restart master to apply.');return 0
        if os.name!='nt':raise RuntimeError('This package requires 64-bit Windows.')
        instance=WindowsInstance(root)
        if not instance.acquire():print('master is already running from this folder.');return 0
        (root/'logs').mkdir(exist_ok=True)
        handler=RotatingFileHandler(root/'logs/server.log',maxBytes=5_000_000,backupCount=3,encoding='utf-8')
        console=logging.StreamHandler()
        logging.basicConfig(level=logging.INFO,handlers=[handler,console],format='%(asctime)s %(levelname)s %(message)s',force=True)
        data=root/'data';data.mkdir(exist_ok=True)
        (root/'config').mkdir(exist_ok=True)
        os.environ['MATHMASTER_DATA']=str(data)
        os.environ['MATHMASTER_AI_PROVIDER_FILE']=str(root/'config/provider.json')
        os.environ['MATHMASTER_EMBEDDING_MODEL_DIR']=str(data/'models/bge-small-zh-v1.5')
        os.environ['MATHMASTER_START_INDEXER']='1' if config['background_indexing'] else '0'
        os.environ['MATHMASTER_NO_BROWSER']='1'
        os.environ['PYTHONUTF8']='1'
        port=config['port']
        origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}',*config['public_origins']}
        hosts={socket.gethostname()}
        try:hosts.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET))
        except OSError:pass
        for host in hosts:
            if not host.startswith(('169.254.','198.18.','198.19.')):origins.add(f'http://{host}:{port}')
        os.environ['MATHMASTER_ALLOWED_ORIGINS']=','.join(sorted(origins))
        import uvicorn
        from .app import app
        app.title='master'
        server=uvicorn.Server(uvicorn.Config(app,host=config['host'],port=port,log_config=None,access_log=False,
                                            proxy_headers=True,forwarded_allow_ips='127.0.0.1,::1',timeout_graceful_shutdown=20))
        closed=threading.Event()
        def monitor():
            while not closed.is_set():
                if instance.kernel.WaitForSingleObject(instance.event,250)==0:
                    server.should_exit=True;return
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        print(f'master listening on {config["host"]}:{port}',flush=True)
        print(f'Local: http://127.0.0.1:{port}',flush=True)
        for origin in config['public_origins']:print('Public: '+origin,flush=True)
        print('Keep this window open. Use stop.bat to stop.',flush=True)
        try:server.run()
        finally:closed.set();watcher.join(timeout=2)
        return 0 if server.started else 1
    except Exception:
        logging.exception('master could not start.');return 1
    finally:
        if instance:instance.close()


if __name__=='__main__':raise SystemExit(main())
