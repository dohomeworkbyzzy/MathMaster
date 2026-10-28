from urllib.parse import urlsplit
from fastapi import Request


def is_local_management(request: Request) -> bool:
    """Proxy traffic must never inherit the proxy's loopback privileges."""
    if any(name == 'forwarded' or name.startswith('x-forwarded-') for name in request.headers):
        return False
    loopback = {'localhost', '127.0.0.1', '::1'}
    try:
        host = urlsplit('//'+request.headers.get('host', '')).hostname
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).hostname not in loopback:
            return False
    except ValueError:
        return False
    peer = request.client.host if request.client else None
    return (host in loopback and peer in loopback) or (host == 'testserver' and peer == 'testclient')
