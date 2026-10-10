#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef ProjectRoot
  #error ProjectRoot must be supplied by the build script
#endif

[Setup]
AppId={{D8B0AA67-F026-4D95-BA31-47A267E25AE1}
AppName=MathMaster
AppVersion={#AppVersion}
AppPublisher=zzy
AppPublisherURL=https://github.com/dohomeworkbyzzy/MathMaster
AppSupportURL=https://github.com/dohomeworkbyzzy/MathMaster/issues
AppUpdatesURL=https://github.com/dohomeworkbyzzy/MathMaster/releases
DefaultDirName={localappdata}\Programs\MathMaster
DefaultGroupName=MathMaster
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
LicenseFile={#ProjectRoot}\LICENSE
SetupIconFile={#ProjectRoot}\packaging\windows\mathmaster.ico
UninstallDisplayIcon={app}\MathMaster.exe
OutputDir={#ProjectRoot}\artifacts
OutputBaseFilename=MathMaster-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create desktop shortcut"; GroupDescription: "快捷方式 / Shortcuts:"

[Files]
Source: "{#ProjectRoot}\artifacts\windows\MathMaster\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\LICENSE"; DestDir: "{app}"
Source: "{#ProjectRoot}\artifacts\MathMaster-{#AppVersion}-local.zip"; DestDir: "{app}\source"; Flags: ignoreversion

[Icons]
Name: "{group}\MathMaster"; Filename: "{app}\MathMaster.exe"
Name: "{group}\操作手册"; Filename: "https://github.com/dohomeworkbyzzy/MathMaster/blob/main/docs/使用手册.md"
Name: "{group}\退出 MathMaster"; Filename: "{app}\MathMaster.exe"; Parameters: "--quit"
Name: "{group}\卸载 MathMaster"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MathMaster"; Filename: "{app}\MathMaster.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MathMaster.exe"; Description: "启动 MathMaster / Launch MathMaster"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\MathMaster.exe"; Parameters: "--quit"; RunOnceId: "StopMathMaster"; Flags: runhidden waituntilterminated skipifdoesntexist

; User data in LOCALAPPDATA\MathMaster\data is deliberately never deleted.
