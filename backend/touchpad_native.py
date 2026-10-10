"""Windows Raw Input touchpad reader. No drivers, hooks, or synthetic mouse input.

The HID approach was researched against arpruss/finger-draw (MIT) and Microsoft's
Raw Input/HID documentation. This module owns no OS settings and never moves the
system cursor. Run --probe for read-only device discovery, otherwise JSONL frames.
"""
import ctypes as c
import json
import os
import sys
from .cursor_lock import CursorLock
from .desktop_focus import BROWSERS, workspace_title

U16 = c.c_uint16
U32 = c.c_uint32
I32 = c.c_int32
PTR = c.c_void_p


class Device(c.Structure):
    _fields_ = [('handle', PTR), ('kind', U32)]


class Caps(c.Structure):
    _fields_ = [('usage', U16), ('page', U16), ('input_length', U16),
                ('output_length', U16), ('feature_length', U16), ('reserved', U16 * 17),
                ('links', U16), ('input_buttons', U16), ('input_values', U16),
                ('input_data', U16), ('output_buttons', U16), ('output_values', U16),
                ('output_data', U16), ('feature_buttons', U16), ('feature_values', U16),
                ('feature_data', U16)]


class UsageRange(c.Structure):
    _fields_ = [('min', U16), ('max', U16), ('string_min', U16), ('string_max', U16),
                ('designator_min', U16), ('designator_max', U16), ('data_min', U16), ('data_max', U16)]


class ValueCaps(c.Structure):
    _fields_ = [('page', U16), ('report', c.c_uint8), ('alias', c.c_uint8),
                ('bit_field', U16), ('link', U16), ('link_usage', U16), ('link_page', U16),
                ('is_range', c.c_uint8), ('string_range', c.c_uint8),
                ('designator_range', c.c_uint8), ('absolute', c.c_uint8),
                ('has_null', c.c_uint8), ('reserved', c.c_uint8), ('bit_size', U16),
                ('report_count', U16), ('reserved2', U16 * 5), ('units_exp', U32),
                ('units', U32), ('logical_min', I32), ('logical_max', I32),
                ('physical_min', I32), ('physical_max', I32), ('usages', UsageRange)]


class Header(c.Structure):
    _fields_ = [('kind', U32), ('size', U32), ('device', PTR), ('wparam', c.c_size_t)]


class ButtonCaps(c.Structure):
    _fields_ = ValueCaps._fields_[:11] + [('reserved', U32 * 10), ('usages', UsageRange)]


def configure(dll, name, restype, args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, args
    return fn


class Reader:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('原始触控板输入需要在 Windows 下通过 start.bat 启动。')
        self.user = c.WinDLL('user32', use_last_error=True)
        self.hid = c.WinDLL('hid', use_last_error=True)
        self.list = configure(self.user, 'GetRawInputDeviceList', U32, [PTR, PTR, U32])
        self.info = configure(self.user, 'GetRawInputDeviceInfoW', U32, [PTR, U32, PTR, PTR])
        self.get_caps = configure(self.hid, 'HidP_GetCaps', I32, [PTR, PTR])
        self.get_values = configure(self.hid, 'HidP_GetValueCaps', I32, [I32, PTR, PTR, PTR])
        self.get_buttons = configure(self.hid, 'HidP_GetButtonCaps', I32, [I32, PTR, PTR, PTR])
        self.get_value = configure(self.hid, 'HidP_GetUsageValue', I32, [I32, U16, U16, U16, PTR, PTR, PTR, U32])
        self.get_usages = configure(self.hid, 'HidP_GetUsages', I32, [I32, U16, U16, PTR, PTR, PTR, PTR, U32])
        self.devices = {}
        self.mice = set()
        self.last_contact = None
        self.frame_count = 0
        self.touching = False

    def discover(self):
        count = U32()
        if self.list(None, c.byref(count), c.sizeof(Device)) == 0xffffffff:
            raise c.WinError(c.get_last_error())
        if count.value > 1024:
            raise RuntimeError('输入设备数超过限制。')
        devices = (Device * count.value)()
        if self.list(devices, c.byref(count), c.sizeof(Device)) == 0xffffffff:
            raise c.WinError(c.get_last_error())
        found = []
        names = {}
        for device in devices:
            size = U32()
            self.info(device.handle, 0x20000007, None, c.byref(size))
            name = c.create_unicode_buffer(min(size.value + 1, 4096))
            length = U32(len(name))
            self.info(device.handle, 0x20000007, name, c.byref(length))
            names[device.handle] = name.value
            if device.kind != 2:
                continue
            size = U32()
            self.info(device.handle, 0x20000005, None, c.byref(size))
            if not 0 < size.value <= 65536:
                continue
            preparsed = c.create_string_buffer(size.value)
            if self.info(device.handle, 0x20000005, preparsed, c.byref(size)) == 0xffffffff:
                continue
            caps = Caps()
            if self.get_caps(preparsed, c.byref(caps)) < 0 or (caps.page, caps.usage) != (13, 5):
                continue
            values = (ValueCaps * caps.input_values)()
            n = U16(caps.input_values)
            if self.get_values(0, values, c.byref(n), preparsed) < 0:
                continue
            groups = {}
            for cap in values[:n.value]:
                if cap.page == 1:
                    for usage in (0x30, 0x31):
                        if cap.usages.min == usage or (cap.is_range and cap.usages.min <= usage <= cap.usages.max):
                            groups.setdefault(cap.link, {})[usage] = cap
            groups = {link: pair for link, pair in groups.items()
                      if len(pair) == 2 and all(v.logical_max > v.logical_min for v in pair.values())}
            if not groups:
                continue
            buttons = (ButtonCaps * caps.input_buttons)()
            nb = U16(caps.input_buttons)
            confidence = set()
            if self.get_buttons(0, buttons, c.byref(nb), preparsed) >= 0:
                for cap in buttons[:nb.value]:
                    if cap.page == 13 and (cap.usages.min == 0x47 or
                            (cap.is_range and cap.usages.min <= 0x47 <= cap.usages.max)):
                        confidence.add(cap.link)
            self.devices[device.handle] = (preparsed, groups, confidence)
            first = next(iter(groups.values()))
            xcap, ycap = first[0x30], first[0x31]
            ratio = (xcap.logical_max-xcap.logical_min)/(ycap.logical_max-ycap.logical_min)
            if xcap.units == ycap.units and xcap.units_exp == ycap.units_exp and \
                    xcap.physical_max > xcap.physical_min and ycap.physical_max > ycap.physical_min:
                ratio = (xcap.physical_max-xcap.physical_min)/(ycap.physical_max-ycap.physical_min)
            found.append({'name': name.value, 'contacts': len(groups),
                          'x_range': [first[0x30].logical_min, first[0x30].logical_max],
                          'y_range': [first[0x31].logical_min, first[0x31].logical_max],
                          'aspect_ratio': ratio})
        # Exclude the mouse collection of the same physical touchpad.
        pad_prefixes = [d['name'].upper().split('&COL')[0] for d in found]
        for device in devices:
            if device.kind == 0 and not any(names[device.handle].upper().startswith(p) for p in pad_prefixes):
                self.mice.add(device.handle)
        return {'available': bool(found), 'devices': found, 'external_mice': len(self.mice),
                'message': '' if found else '未发现提供绝对坐标的 Windows Precision Touchpad。',
                'raw_frames': self.frame_count}

    def read_value(self, preparsed, report, page, link, usage):
        value = U32()
        if self.get_value(0, page, link, usage, c.byref(value), preparsed, report, len(report)) < 0:
            return None
        return value.value

    def contact(self, handle, raw):
        preparsed, groups, confidence = self.devices[handle]
        report = c.create_string_buffer(raw, len(raw))
        count = self.read_value(preparsed, report, 13, 0, 0x54)
        # Serial/hybrid devices may send a zero count for a continuation report.
        active = []
        readable = False
        for link, pair in groups.items():
            usages = (U16 * 128)()
            length = U32(len(usages))
            status = self.get_usages(0, 13, link, usages, c.byref(length), preparsed, report, len(raw))
            if status < 0:
                continue
            readable = True
            pressed = set(usages[:length.value])
            if 0x42 not in pressed:
                continue
            if link in confidence and 0x47 not in pressed:
                continue  # A palm/unreliable contact must never become ink.
            x = self.read_value(preparsed, report, 1, link, 0x30)
            y = self.read_value(preparsed, report, 1, link, 0x31)
            identity = self.read_value(preparsed, report, 13, link, 0x51)
            if x is None or y is None:
                continue
            nx = (x - pair[0x30].logical_min) / (pair[0x30].logical_max - pair[0x30].logical_min)
            ny = (y - pair[0x31].logical_min) / (pair[0x31].logical_max - pair[0x31].logical_min)
            active.append((identity if identity is not None else link, nx, ny))
        if not readable:
            return
        self.frame_count += 1
        self.touching = bool(active)
        # Multi-finger gestures lift the pen; never join unrelated fingers into one stroke.
        if len(active) != 1 or (count is not None and count > 1):
            self.lift()
            return
        identity, x, y = active[0]
        if self.last_contact is not None and self.last_contact != identity:
            self.lift()
        self.last_contact = identity
        emit({'type': 'contact', 'down': True, 'id': identity,
              'x': min(1, max(0, x)), 'y': min(1, max(0, y))})

    def lift(self):
        if self.last_contact is not None:
            self.last_contact = None
            emit({'type': 'contact', 'down': False})

    def run(self):
        from ctypes import wintypes as w
        callback = c.WINFUNCTYPE(c.c_ssize_t, PTR, U32, c.c_size_t, c.c_ssize_t)
        class WindowClass(c.Structure):
            _fields_ = [('style', U32), ('proc', callback), ('cls_extra', I32), ('wnd_extra', I32),
                        ('instance', PTR), ('icon', PTR), ('cursor', PTR), ('background', PTR),
                        ('menu', c.c_wchar_p), ('name', c.c_wchar_p)]
        class Registration(c.Structure):
            _fields_ = [('page', U16), ('usage', U16), ('flags', U32), ('window', PTR)]
        default = configure(self.user, 'DefWindowProcW', c.c_ssize_t, [PTR, U32, c.c_size_t, c.c_ssize_t])
        get_raw = configure(self.user, 'GetRawInputData', U32, [PTR, U32, PTR, PTR, U32])
        foreground = configure(self.user, 'GetForegroundWindow', PTR, [])
        title = configure(self.user, 'GetWindowTextW', I32, [PTR, PTR, I32])
        cursor = configure(self.user, 'GetCursorPos', I32, [PTR])
        class Rect(c.Structure):
            _fields_ = [('left', I32), ('top', I32), ('right', I32), ('bottom', I32)]
        get_clip = configure(self.user, 'GetClipCursor', I32, [PTR])
        clip_cursor = configure(self.user, 'ClipCursor', I32, [PTR])
        def read_bounds():
            rect = Rect()
            if not get_clip(c.byref(rect)):
                raise c.WinError(c.get_last_error())
            return (rect.left, rect.top, rect.right, rect.bottom)
        def confine(bounds):
            rect = Rect(*bounds) if bounds is not None else None
            if not clip_cursor(c.byref(rect) if rect else None):
                raise c.WinError(c.get_last_error())
        initial_cursor = w.POINT()
        cursor(c.byref(initial_cursor))
        cursor_lock = CursorLock(read_bounds, confine, (initial_cursor.x, initial_cursor.y))
        kernel = c.WinDLL('kernel32', use_last_error=True)
        window_pid = configure(self.user, 'GetWindowThreadProcessId', U32, [PTR, PTR])
        open_process = configure(kernel, 'OpenProcess', PTR, [U32, I32, U32])
        process_name = configure(kernel, 'QueryFullProcessImageNameW', I32, [PTR, U32, PTR, PTR])
        close_handle = configure(kernel, 'CloseHandle', I32, [PTR])
        browser_cache = {}
        pending_mouse = False
        active_window = None
        def focused():
            win = foreground()
            text = c.create_unicode_buffer(512)
            title(win, text, len(text))
            if not workspace_title(text.value):
                return None
            pid = U32()
            window_pid(win, c.byref(pid))
            if pid.value not in browser_cache:
                process_handle = open_process(0x1000, False, pid.value)
                image = c.create_unicode_buffer(4096)
                length = U32(len(image))
                supported = False
                if process_handle:
                    try:
                        if process_name(process_handle, 0, image, c.byref(length)):
                            supported = image.value.rsplit('\\', 1)[-1].lower() in BROWSERS
                    finally:
                        close_handle(process_handle)
                if len(browser_cache) > 128:
                    browser_cache.clear()
                browser_cache[pid.value] = supported
            return win if browser_cache[pid.value] else None
        @callback
        def process(window, message, wp, lp):
            nonlocal pending_mouse, active_window
            try:
                if message == 0x00ff:
                    target = focused()
                    if not target:
                        if active_window:
                            cursor_lock.release(); self.lift(); emit({'type': 'pause'})
                        active_window = None
                        return default(window, message, wp, lp)
                    active_window = target
                    size = U32()
                    get_raw(lp, 0x10000003, None, c.byref(size), c.sizeof(Header))
                    if 0 < size.value <= 65536:
                        raw = c.create_string_buffer(size.value)
                        if get_raw(lp, 0x10000003, raw, c.byref(size), c.sizeof(Header)) != 0xffffffff:
                            header = Header.from_buffer(raw)
                            if header.kind == 2 and header.device in self.devices:
                                offset = c.sizeof(Header)
                                length = U32.from_buffer(raw, offset).value
                                count = U32.from_buffer(raw, offset + 4).value
                                if length and count * length + offset + 8 <= size.value:
                                    for i in range(count):
                                        self.contact(header.device, raw.raw[offset+8+i*length:offset+8+(i+1)*length])
                                        cursor_lock.touch(self.touching)
                            elif header.kind == 0 and header.device in self.mice:
                                cursor_lock.external_mouse()
                                pending_mouse = True
                    # Required for cleanup of foreground WM_INPUT messages.
                    return default(window, message, wp, lp)
                if message == 0x0113 and pending_mouse:
                    pending_mouse = False
                    if focused():
                        point = w.POINT()
                        cursor(c.byref(point))
                        cursor_lock.anchor = (point.x, point.y)
                        emit({'type': 'mouse', 'screen_x': point.x, 'screen_y': point.y})
                if message == 0x0113 and active_window and not focused():
                    active_window = None
                    cursor_lock.release(); self.lift(); emit({'type': 'pause'})
                if message == 0x0010:
                    cursor_lock.release()
                    configure(self.user, 'DestroyWindow', I32, [PTR])(window)
                    return 0
                if message == 0x0002:
                    self.user.PostQuitMessage(0)
                    return 0
            except Exception as e:
                cursor_lock.release()
                emit({'type': 'error', 'message': str(e)})
            return default(window, message, wp, lp)
        instance = configure(kernel, 'GetModuleHandleW', PTR, [c.c_wchar_p])(None)
        name = 'MathMasterRawTouchpad'
        wc = WindowClass(0, process, 0, 0, instance, None, None, None, None, name)
        register_class = configure(self.user, 'RegisterClassW', U16, [PTR])
        if not register_class(c.byref(wc)):
            raise c.WinError(c.get_last_error())
        create = configure(self.user, 'CreateWindowExW', PTR,
                           [U32, c.c_wchar_p, c.c_wchar_p, U32, I32, I32, I32, I32, PTR, PTR, PTR, PTR])
        window = create(0, name, name, 0, 0, 0, 0, 0, PTR(-3), None, instance, None)
        if not window:
            raise c.WinError(c.get_last_error())
        registrations = (Registration * 2)(Registration(13, 5, 0x100, window), Registration(1, 2, 0x100, window))
        register = configure(self.user, 'RegisterRawInputDevices', I32, [PTR, U32, U32])
        if not register(registrations, 2, c.sizeof(Registration)):
            raise c.WinError(c.get_last_error())
        configure(self.user, 'SetTimer', c.c_size_t, [PTR, c.c_size_t, U32, PTR])(window, 1, 16, None)
        emit({'type': 'ready', 'window_handle': int(window), 'cursor_lock': True, **self.discover()})
        msg = w.MSG()
        get_message = configure(self.user, 'GetMessageW', I32, [PTR, PTR, U32, U32])
        dispatch = configure(self.user, 'DispatchMessageW', c.c_ssize_t, [PTR])
        try:
            while get_message(c.byref(msg), None, 0, 0) > 0:
                self.user.TranslateMessage(c.byref(msg))
                dispatch(c.byref(msg))
        finally:
            cursor_lock.release()


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    try:
        reader = Reader()
        status = reader.discover()
        if '--probe' in sys.argv:
            emit(status)
        elif status['available']:
            reader.run()
        else:
            emit({'type': 'error', **status})
            return 1
    except Exception as e:
        emit({'type': 'error', 'available': False, 'message': str(e)})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
