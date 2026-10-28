"""Standalone helper with the same isolated native reader as the desktop app."""
import runpy
import sys

if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    worker = len(sys.argv) > 1 and sys.argv[1] == '--touchpad-worker'
    runpy.run_module('backend.touchpad_native' if worker else 'backend.touchpad_helper', run_name='__main__')
