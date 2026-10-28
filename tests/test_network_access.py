from fastapi.testclient import TestClient
from backend import app as module


def test_public_origin_is_explicit_and_checked_on_writes(monkeypatch):
    origin = 'https://configured.example'
    monkeypatch.setattr(module, 'NETWORK_ALLOWED_ORIGINS', frozenset({origin}))
    monkeypatch.delenv('MATHMASTER_ALLOWED_ORIGINS', raising=False)

    @module.app.post('/_network_access_test')
    def probe():
        return {'ok': True}

    try:
        client = TestClient(module.app)
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/health', headers={'Host': 'configured.example'}).status_code == 200
        assert client.post('/_network_access_test', headers={'Host': 'configured.example', 'Origin': origin}).status_code == 200
        assert client.get('/api/health', headers={'Host': 'unconfigured.example'}).status_code == 403
        assert client.get('/api/health', headers={'Host': 'configured.example.attacker.test'}).status_code == 403
        assert client.post('/_network_access_test', headers={'Host': 'configured.example', 'Origin': 'https://unconfigured.example'}).status_code == 403
        assert client.post('/_network_access_test', headers={'Host': 'configured.example', 'Origin': 'http://configured.example'}).status_code == 403
        monkeypatch.setattr(module, 'NETWORK_ALLOWED_ORIGINS', frozenset())
        assert client.get('/api/health', headers={'Host': 'configured.example'}).status_code == 403
    finally:
        module.app.router.routes[:] = [r for r in module.app.router.routes if getattr(r, 'path', '') != '/_network_access_test']


def test_remote_config_is_names_only_and_only_allows_activation(monkeypatch):
    from backend.ai import profiles, provider
    monkeypatch.setattr(module, 'NETWORK_ALLOWED_ORIGINS', frozenset({'https://configured.example'}))
    monkeypatch.setattr(profiles, 'read', lambda: {'profiles': [{
        'id': 'private-id', 'kind': 'chat', 'model_id': 'visible-model',
        'provider_name': 'private-provider', 'base_url': 'https://private-endpoint.example',
        'api_key': 'private-key', 'extra_body': {'secret': 'private-param'}}]})
    monkeypatch.setattr(provider, 'public_profile', lambda: {
        'configured': True, 'model_id': 'visible-model', 'model_name': 'Visible model',
        'base_url': 'https://private-endpoint.example', 'capabilities': {'base_url': 'private-url'},
        'protocol': 'private-protocol'})
    client = TestClient(module.app)
    headers = {'Host': 'configured.example', 'Origin': 'https://configured.example'}
    result = client.get('/api/ai/profiles', headers=headers)
    assert result.json() == {'read_only': True, 'can_activate': True, 'active_chat': None, 'active_embedding': None, 'profiles': [{'id': 'private-id', 'kind': 'chat', 'model_id': 'visible-model'}]}
    assert result.headers['cache-control'] == 'no-store'
    monkeypatch.setattr(profiles, 'activate', lambda pid: {**profiles.read(), 'active_chat': pid})
    switched = client.post('/api/ai/profiles/private-id/activate', headers=headers)
    assert switched.status_code == 200
    assert switched.json()['active_chat'] == 'private-id'
    assert sorted(switched.json()['profiles'][0]) == ['id', 'kind', 'model_id']
    assert not any(value in switched.text for value in ('private-provider', 'private-endpoint', 'private-key', 'private-param'))
    assert switched.headers['cache-control'] == 'no-store'
    assert client.get('/api/ai/provider', headers=headers).json() == {
        'configured': True, 'model_id': 'visible-model', 'model_name': 'Visible model'}
    for method, path in [('POST', '/api/ai/profiles'), ('DELETE', '/api/ai/profiles/private-id'),
                         ('POST', '/api/ai/profiles/private-id/test'),
                         ('GET', '/api/ai/profiles/private-id/models'), ('PUT', '/api/ai/provider'),
                         ('POST', '/api/ai/provider/test'), ('PUT', '/api/ai/provider/reasoning'),
                         ('GET', '/api/ai/embeddings/status'), ('PUT', '/api/ai/embeddings/auto'),
                         ('POST', '/api/ai/embeddings/rebuild')]:
        assert client.request(method, path, headers=headers).status_code == 403


def test_proxy_cannot_gain_local_management_by_rewriting_host(monkeypatch):
    from backend.network_access import is_local_management
    from starlette.requests import Request
    def check(host, peer='127.0.0.1', extra=()):
        return is_local_management(Request({'type': 'http', 'headers': [(b'host', host.encode()), *extra],
                                           'client': (peer, 1234)}))
    assert check('127.0.0.1:8765')
    assert check('[::1]:8765', peer='::1')
    assert not check('configured.example')
    assert not check('127.0.0.1:8765', peer='192.168.1.2')
    assert not check('127.0.0.1:8765', extra=[(b'x-forwarded-for', b'127.0.0.1')])
    assert not check('127.0.0.1:8765', extra=[(b'x-forwarded-host', b'configured.example')])
    assert not check('127.0.0.1:8765', extra=[(b'origin', b'https://configured.example')])
