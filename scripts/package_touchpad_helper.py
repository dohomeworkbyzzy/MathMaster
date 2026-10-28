"""Run with the Windows build Python; creates the browser-downloadable helper ZIP."""
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(ROOT/'build/touchpad-helper/dist'),
                    '--workpath', str(ROOT/'build/touchpad-helper/work'),
                    str(ROOT/'packaging/windows/TouchpadHelper.spec')], cwd=ROOT, check=True)
    output = ROOT/'public/assets/MathMasterTouchpad.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/'build/touchpad-helper/dist/MathMasterTouchpad.exe', 'MathMasterTouchpad.exe')
        archive.writestr('README.txt', 'MathMaster Touchpad\r\n\r\n1. Extract the ZIP and run MathMasterTouchpad.exe.\r\n2. Keep the window open and connect an external mouse.\r\n3. Click the touchpad button on your MathMaster page and enter the 8-digit code.\r\n4. Allow the helper connection popup and keep it open.\r\n5. Move the external mouse over the draft to select the writing position.\r\n6. Press Ctrl+C in the helper window to exit.\r\n\r\nRequires Windows and a supported Precision Touchpad. No Python installation required.\r\nThe local connection window supports public HTTP and HTTPS pages.\r\n')
    print(output)


if __name__ == '__main__':
    main()
