"""Read-only Windows HID checks. Reports below are synthesized in memory only.

This checks decoding against this machine's real HID descriptor; it does not send
input to Windows or claim a finger was physically moved on the touchpad.
"""
import ctypes as c
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import touchpad_native as native
from backend.touchpad import bridge
from backend.touchpad import ClipRect, clip_snapshot
from backend.cursor_lock import CursorLock


def main():
    reader = native.Reader()
    info = reader.discover()
    if not info['available']:
        raise RuntimeError(info['message'])
    handle, (preparsed, groups, confidence) = next(iter(reader.devices.items()))
    caps = native.Caps()
    assert reader.get_caps(preparsed, c.byref(caps)) >= 0
    link, pair = next(iter(groups.items()))
    initialize = native.configure(reader.hid, 'HidP_InitializeReportForID', native.I32,
                                  [native.I32, c.c_uint8, native.PTR, native.PTR, native.U32])
    set_value = native.configure(reader.hid, 'HidP_SetUsageValue', native.I32,
                                [native.I32, native.U16, native.U16, native.U16, native.U32,
                                 native.PTR, native.PTR, native.U32])
    set_usages = native.configure(reader.hid, 'HidP_SetUsages', native.I32,
                                 [native.I32, native.U16, native.U16, native.PTR, native.PTR,
                                  native.PTR, native.PTR, native.U32])
    events = []
    native.emit = events.append
    def report(down, fingers=1, identity=7, palm=False):
        data = c.create_string_buffer(caps.input_length)
        assert initialize(0, pair[0x30].report, preparsed, data, len(data)) >= 0
        for usage, fraction in [(0x30, .25), (0x31, .75)]:
            cap = pair[usage]
            value = round(cap.logical_min + (cap.logical_max-cap.logical_min)*fraction)
            assert set_value(0, 1, link, usage, value, preparsed, data, len(data)) >= 0
        assert set_value(0, 13, link, 0x51, identity, preparsed, data, len(data)) >= 0
        assert set_value(0, 13, 0, 0x54, fingers, preparsed, data, len(data)) >= 0
        if down:
            usages = [0x42] + ([0x47] if link in confidence and not palm else [])
            values = (native.U16 * len(usages))(*usages)
            count = native.U32(len(usages))
            assert set_usages(0, 13, link, values, c.byref(count), preparsed, data, len(data)) >= 0
        reader.contact(handle, data.raw)
    report(True)
    assert events[-1]['down'] is True
    assert abs(events[-1]['x']-.25) <= 1/(pair[0x30].logical_max-pair[0x30].logical_min)
    assert abs(events[-1]['y']-.75) <= 1/(pair[0x31].logical_max-pair[0x31].logical_min)
    report(False, fingers=0)
    assert events[-1]['down'] is False
    report(True); report(True, fingers=2)
    assert events[-1]['down'] is False
    report(True, identity=2); report(True, identity=3)
    assert events[-2]['down'] is False and events[-1]['id'] == 3
    if link in confidence:
        report(True, palm=True)
        assert events[-1]['down'] is False
    # Briefly confine at the existing pointer (no movement), then verify restoration.
    from ctypes import wintypes as w
    point=w.POINT()
    c.windll.user32.GetCursorPos(c.byref(point))
    previous=clip_snapshot()
    def clip(rect):
        if not c.windll.user32.ClipCursor(c.byref(ClipRect(*rect))):
            raise c.WinError(c.get_last_error())
    guard=CursorLock(clip_snapshot,clip,(point.x,point.y))
    try:
        guard.touch(True)
        assert clip_snapshot()==(point.x,point.y,point.x+1,point.y+1)
        guard.external_mouse()
        assert clip_snapshot()==previous
    finally:
        clip(previous)
    session = bridge.start()
    try:
        assert session['available']
        try:
            bridge.start()
        except ValueError:
            pass
        else:
            raise AssertionError('Parallel session was accepted')
        try:
            bridge.stop('wrong-token')
        except ValueError:
            pass
        else:
            raise AssertionError('Incorrect owner token was accepted')
    finally:
        bridge.stop(session['token'])
    assert bridge.session.process.poll() is not None
    print(json.dumps({'descriptor': info, 'decoder_checks': 'passed',
                      'native_process_start_stop': 'passed',
                      'native_cursor_lock_release': 'passed',
                      'physical_handwriting_test': 'not_performed'}, ensure_ascii=True))


if __name__ == '__main__':
    main()
