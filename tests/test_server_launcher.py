import json
import pytest
from backend.server_launcher import settings,validate_origin


def test_server_binding_and_origin_configuration(tmp_path):
    default=settings(tmp_path)
    assert default['host']=='0.0.0.0' and default['port']==8509
    assert default['public_origins']==['http://39.129.11.4:8509']
    (tmp_path/'config.json').write_text(json.dumps({'port':18509,'public_origins':['https://example.test/'],'background_indexing':False}))
    updated=settings(tmp_path)
    assert updated['port']==18509 and updated['public_origins']==['https://example.test']
    assert not updated['background_indexing']


@pytest.mark.parametrize('url',['https://user:password@example.test','https://example.test/path','file:///etc/passwd','https://example.test?token=x','http://example.test:99999','https://example.test/#fragment'])
def test_server_rejects_invalid_public_origins(url):
    with pytest.raises(ValueError):validate_origin(url)


@pytest.mark.parametrize('port',[0,65536,True,'8509'])
def test_server_rejects_invalid_listening_ports(tmp_path,port):
    (tmp_path/'config.json').write_text(json.dumps({'port':port}))
    with pytest.raises(ValueError):settings(tmp_path)
