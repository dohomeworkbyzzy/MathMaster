import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.app import app

@pytest.mark.parametrize('suffix',['.png','.jpg','.jpeg','.webp','.JPG','.pdf'])
def test_library_media_formats_are_served_without_altering_bytes(tmp_path,monkeypatch,suffix):
 monkeypatch.setattr(db,'DATA',tmp_path)
 path=tmp_path/'uploads'/'workbook'/('question'+suffix);path.parent.mkdir(parents=True);path.write_bytes(b'original media bytes')
 response=TestClient(app).get('/api/files/workbook/'+path.name)
 assert response.status_code==200
 assert response.content==path.read_bytes()

def test_library_executables_and_paths_outside_uploads_are_rejected(tmp_path,monkeypatch):
 monkeypatch.setattr(db,'DATA',tmp_path)
 (tmp_path/'uploads').mkdir();(tmp_path/'uploads/q.exe').write_bytes(b'not an image')
 client=TestClient(app)
 assert client.get('/api/files/q.exe').status_code==404
 assert client.get('/api/files/%2e%2e/private.db').status_code==404
