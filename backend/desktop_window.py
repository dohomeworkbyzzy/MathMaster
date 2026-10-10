"""Resize only the foreground MathMaster browser window. No desktop-wide changes."""
import ctypes as c
import os
from threading import RLock

_saved = {}
_lock = RLock()


def change(mode):
    if os.name != 'nt':
        raise ValueError('Windows 小窗口控制需要通过 start.bat 启动；也可手动拖动浏览器窗口边缘。')
    user, kernel = c.WinDLL('user32', use_last_error=True), c.WinDLL('kernel32', use_last_error=True)
    def fn(dll, name, result, args):
        f = getattr(dll, name);f.restype=result;f.argtypes=args;return f
    window = fn(user, 'GetForegroundWindow', c.c_void_p, [])()
    text = c.create_unicode_buffer(512)
    fn(user, 'GetWindowTextW', c.c_int, [c.c_void_p, c.c_void_p, c.c_int])(window, text, len(text))
    pid = c.c_uint32()
    fn(user, 'GetWindowThreadProcessId', c.c_uint32, [c.c_void_p, c.c_void_p])(window, c.byref(pid))
    process = fn(kernel, 'OpenProcess', c.c_void_p, [c.c_uint32, c.c_int, c.c_uint32])(0x1000, False, pid.value)
    image = c.create_unicode_buffer(4096);length=c.c_uint32(len(image))
    try:
        valid = process and fn(kernel, 'QueryFullProcessImageNameW', c.c_int,
                               [c.c_void_p,c.c_uint32,c.c_void_p,c.c_void_p])(process,0,image,c.byref(length))
    finally:
        if process:fn(kernel,'CloseHandle',c.c_int,[c.c_void_p])(process)
    if not valid or 'MathMaster' not in text.value or image.value.rsplit('\\',1)[-1].lower() not in {
            'msedge.exe','chrome.exe','firefox.exe','brave.exe','vivaldi.exe','opera.exe'}:
        raise ValueError('请先切回 MathMaster 窗口，再使用窗口控制。')
    class Rect(c.Structure):
        _fields_=[('left',c.c_int32),('top',c.c_int32),('right',c.c_int32),('bottom',c.c_int32)]
    with _lock:
        rect=Rect()
        fn(user,'GetWindowRect',c.c_int,[c.c_void_p,c.c_void_p])(window,c.byref(rect))
        if mode=='minimize':
            fn(user,'ShowWindow',c.c_int,[c.c_void_p,c.c_int])(window,6)
        else:
            if mode=='compact':
                key=(window,pid.value)
                if key not in _saved:
                    if len(_saved)>32:_saved.clear()
                    _saved[key]=(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top,
                                 bool(fn(user,'IsZoomed',c.c_int,[c.c_void_p])(window)))
                fn(user,'ShowWindow',c.c_int,[c.c_void_p,c.c_int])(window,9)
                fn(user,'GetWindowRect',c.c_int,[c.c_void_p,c.c_void_p])(window,c.byref(rect))
                bounds=(rect.left,rect.top,640,520)
            elif mode=='restore':
                old=_saved.pop((window,pid.value),(rect.left,rect.top,1000,740,False))
                bounds=old[:4]
            else:raise ValueError('未知窗口操作。')
            if not fn(user,'SetWindowPos',c.c_int,[c.c_void_p,c.c_void_p,c.c_int,c.c_int,c.c_int,c.c_int,c.c_uint32])(
                    window,None,*bounds,0x0004|0x0010):
                raise c.WinError(c.get_last_error())
            if mode=='restore' and old[4]:fn(user,'ShowWindow',c.c_int,[c.c_void_p,c.c_int])(window,3)
    return {'mode':mode}
