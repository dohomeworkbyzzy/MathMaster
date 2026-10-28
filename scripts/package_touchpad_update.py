"""Package the shared AI draft and visitor touchpad frontend for existing master.exe."""
import hashlib
from pathlib import Path
import zipfile
from bootstrap import ROOT, source_hash


def main():
    stamp = ROOT/'dist/.source-hash'
    if not stamp.is_file() or stamp.read_text() != source_hash():
        raise SystemExit('Build the current frontend first: npm run build')
    helper = ROOT/'dist/assets/MathMasterTouchpad.zip'
    if not helper.is_file():
        raise SystemExit('Build the Windows touchpad helper before npm run build.')
    with zipfile.ZipFile(helper) as archive:
        assert archive.testzip() is None
        assert 'MathMasterTouchpad.exe' in archive.namelist()
    output = ROOT/'artifacts/master-touchpad-update.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted((ROOT/'dist').rglob('*')):
            if file.is_file():
                archive.write(file, '_internal/dist/'+file.relative_to(ROOT/'dist').as_posix())
        archive.writestr('TOUCHPAD-UPDATE.txt', 'MathMaster frontend update\r\n\r\n1. Back up the existing _internal/dist folder beside master.exe.\r\n2. Extract this ZIP into that folder containing master.exe, replacing _internal/dist.\r\n3. Restart and refresh the browser with Ctrl+F5.\r\n4. Open AI tutoring to use the shared electronic draft.\r\n5. Remote visitors: click the touchpad button, download the helper, run it and enter its pairing code.\r\n6. Allow the helper popup and keep it open while writing.\r\n\r\nThis package contains frontend files only. No databases or API credentials are included.\r\n')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert '_internal/dist/assets/MathMasterTouchpad.zip' in archive.namelist()
        assert all(name.startswith('_internal/dist/') or name == 'TOUCHPAD-UPDATE.txt' for name in archive.namelist())
    output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
    print(output)


if __name__ == '__main__':
    main()
