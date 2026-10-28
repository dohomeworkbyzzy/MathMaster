"""Build the Windows x64 remote client using the native .NET Framework compiler.

Run with .venv-win/Scripts/python.exe from Windows (or through WSL).
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.4258.31'


def main():
    sdk = ROOT / '.tools/webview2/sdk'
    if not (sdk / 'lib/net462/Microsoft.Web.WebView2.Core.dll').exists():
        sdk.mkdir(parents=True, exist_ok=True)
        package = sdk.parent / 'sdk.zip'
        urllib.request.urlretrieve(f'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{VERSION}/microsoft.web.webview2.{VERSION}.nupkg', package)
        with zipfile.ZipFile(package) as archive:
            archive.extractall(sdk)
    output = ROOT / 'artifacts/MathMasterClient-HD'
    output.mkdir(parents=True, exist_ok=True)
    for name in ('Core', 'WinForms'):
        shutil.copy2(sdk / f'lib/net462/Microsoft.Web.WebView2.{name}.dll', output)
    shutil.copy2(sdk / 'runtimes/win-x64/native/WebView2Loader.dll', output)
    compiler = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                    f'/win32manifest:{ROOT / "packaging/windows/remote-client/app.manifest"}',
                    f'/resource:{ROOT / "packaging/windows/remote-client/client.css"},client.css',
                    f'/out:{output / "MathMasterClient.exe"}',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    '/reference:System.Web.Extensions.dll',
                    *[f'/reference:{output / ("Microsoft.Web.WebView2." + name + ".dll")}' for name in ('Core', 'WinForms')],
                    str(ROOT / 'packaging/windows/remote-client/RemoteClient.cs')], check=True)
    (output / 'MathMasterClient.exe.config').write_text('''<?xml version="1.0"?>
<configuration>
  <startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup>
  <System.Windows.Forms.ApplicationConfigurationSection>
    <add key="DpiAwareness" value="PerMonitorV2"/>
  </System.Windows.Forms.ApplicationConfigurationSection>
</configuration>
''', encoding='utf-8')
    (output / 'README.txt').write_text('''MathMaster Client 1.1 - Windows 10/11 x64

Extract the complete ZIP, then double-click MathMasterClient.exe.
Server: http://39.129.11.4:8509

Use the top toolbar to switch to a compact window, restore, pin/unpin,
or reconnect. The page's window buttons also control this computer.
Resize using the window border; minimize using the title bar.
High DPI and mixed-monitor scaling are enabled automatically.
Use A-/A+ to adjust page zoom (80%-200%); click the percentage to reset.
Ctrl+plus/minus/0 also controls zoom. Your zoom level is remembered.
Page images and PDF links open in separate viewer windows.
User selection and page settings persist in %LOCALAPPDATA%/MathMasterClient.
Questions and saved answers use the remote server.

Requires .NET Framework 4.8 and Microsoft Edge WebView2 Runtime.
If WebView2 is missing, install it from Microsoft's official page:
https://developer.microsoft.com/microsoft-edge/webview2/

Third-party notices: THIRD-PARTY-NOTICES.txt
''', encoding='utf-8')
    license_files = [p for p in sdk.iterdir() if 'license' in p.name.lower() or p.name == 'NOTICE.txt']
    (output / 'THIRD-PARTY-NOTICES.txt').write_text(
        'Microsoft.Web.WebView2 SDK ' + VERSION + '\nhttps://www.nuget.org/packages/Microsoft.Web.WebView2/' + VERSION + '\n\n' +
        '\n'.join(p.read_text(encoding='utf-8-sig') for p in license_files if p.is_file()), encoding='utf-8')
    archive_path = ROOT / 'artifacts/MathMasterClient-HD.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, output.name + '/' + path.name)
    print(archive_path)
    print('SHA256:', hashlib.sha256(archive_path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
