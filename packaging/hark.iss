; Inno Setup script for Hark: wraps dist\Hark (built by hark.spec) into a per-user installer.
; Build with packaging\build.ps1, or: iscc /DAppVersion=0.1.0 hark.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{2C8891E0-F711-4396-B859-B7D5570F71DB}
AppName=Hark
AppVersion={#AppVersion}
AppVerName=Hark {#AppVersion}
DefaultDirName={localappdata}\Programs\Hark
DefaultGroupName=Hark
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=HarkSetup-{#AppVersion}
SetupIconFile=hark.ico
UninstallDisplayIcon={app}\Hark.exe
UninstallDisplayName=Hark
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start Hark when I sign in"
Name: "desktopicon"; Description: "Add a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Hark\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Hark"; Filename: "{app}\Hark.exe"
Name: "{group}\Uninstall Hark"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Hark"; Filename: "{app}\Hark.exe"; Tasks: desktopicon

[Registry]
; Same entry as Settings > General > "Start Hark when I sign in".
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Hark"; \
  ValueData: """{app}\Hark.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Hark.exe"; Description: "Start Hark now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Hark.exe /F"; Flags: runhidden; RunOnceId: "StopHark"

; Settings, history and downloaded models in %LOCALAPPDATA%\hark are kept on uninstall.
