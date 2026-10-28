"""Launch isolated workers in both source and self-contained Windows builds."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    'backend.worker': '--math-worker',
    'backend.ai.worker': '--ai-worker',
    'backend.importer': '--import-worker',
    'backend.touchpad_native': '--touchpad-worker',
}


def worker_command(module, *arguments):
    if module not in WORKERS:
        raise ValueError('Unsupported worker module')
    if getattr(sys, 'frozen', False):
        return [sys.executable, WORKERS[module], *arguments]
    return [sys.executable, '-m', module, *arguments]
