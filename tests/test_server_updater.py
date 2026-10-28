"""The updater must reject state files and corrupted archives before shutdown."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile
import pytest

spec = importlib.util.spec_from_file_location('server_updater', Path(__file__).resolve().parents[1] / 'packaging/windows/server_updater.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def package(extra=None, manifest_change=None):
    files = {'master.exe': b'executable', '_internal/dist/index.html': b'frontend', **(extra or {})}
    manifest = {'format': 1, 'product': updater.PRODUCT, 'version': 'test',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    if manifest_change:
        manifest_change(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
    stream.seek(0)
    return stream


@pytest.mark.parametrize('name', ['data/mathmaster.db', 'config/provider.json', 'config.json',
                                '_internal/../../data/mathmaster.db', '_internal/../data/x',
                                '_internal/\\temp', '_internal/C:/bad'])
def test_package_cannot_overwrite_state_or_escape(name):
    with zipfile.ZipFile(package({name: b'bad'})) as archive:
        with pytest.raises(ValueError):
            updater.read_manifest(archive)


def test_corrupt_package_fails_before_installation(tmp_path):
    stream = package(manifest_change=lambda m: m['files'].update({'master.exe': '0' * 64}))
    with pytest.raises(ValueError, match='校验失败'):
        updater.extract_verified(stream, tmp_path, lambda text: None)
    assert not (tmp_path / '_internal').exists()


def test_case_collisions_and_incomplete_runtime_are_rejected():
    with zipfile.ZipFile(package({'_internal/DIST/INDEX.HTML': b'duplicate'})) as archive:
        with pytest.raises(ValueError, match='重复'):
            updater.read_manifest(archive)
    with zipfile.ZipFile(package(manifest_change=lambda m: m['files'].pop('master.exe'))) as archive:
        with pytest.raises(ValueError):
            updater.read_manifest(archive)


def test_valid_package_extracts_exact_hashes(tmp_path):
    manifest = updater.extract_verified(package(), tmp_path, lambda text: None)
    assert set(manifest['files']) == {'master.exe', '_internal/dist/index.html'}
    assert (tmp_path / 'master.exe').read_bytes() == b'executable'
    assert (tmp_path / '_internal/dist/index.html').read_bytes() == b'frontend'
