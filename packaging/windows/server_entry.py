"""Portable server executable and isolated worker dispatch."""
import runpy
import sys


if __name__ == '__main__':
    from backend.runtime import WORKERS
    workers={flag:module for module,flag in WORKERS.items()}
    if len(sys.argv)>1 and sys.argv[1] in workers:
        for stream in (sys.stdin,sys.stdout,sys.stderr):
            if stream and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
        runpy.run_module(workers[sys.argv[1]],run_name='__main__')
    else:
        from backend.server_launcher import main
        raise SystemExit(main())
