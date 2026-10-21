; Inno Setup script for Togo: wraps dist\Togo (built by togo.spec) into a per-user installer.
; Build with packaging\build.ps1, or: iscc /DAppVersion=0.1.0 togo.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{342C464F-EB83-4886-9BE8-5D3F89056132}
AppName=Togo
AppVersion={#AppVersion}
AppVerName=Togo {#AppVersion}
DefaultDirName={localappdata}\Programs\Togo
DefaultGroupName=Togo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=TogoSetup-{#AppVersion}
SetupIconFile=togo.ico
UninstallDisplayIcon={app}\Togo.exe
UninstallDisplayName=Togo
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start Togo when I sign in"
Name: "desktopicon"; Description: "Add a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Togo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Togo"; Filename: "{app}\Togo.exe"
Name: "{group}\Uninstall Togo"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Togo"; Filename: "{app}\Togo.exe"; Tasks: desktopicon

[Registry]
; Same entry as Settings > General > "Start Togo when I sign in".
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Togo"; \
  ValueData: """{app}\Togo.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Togo.exe"; Description: "Start Togo now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop only the copy installed here: a Togo run from elsewhere (e.g. from source) shares the name.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-Process Togo,togo-mcp -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "StopTogo"

[UninstallDelete]
; Folders the app made at runtime (e.g. caches) aren't in the uninstall log; clear the whole install folder.
Type: filesandordirs; Name: "{app}"

; Settings, history and downloaded models in %LOCALAPPDATA%\togo are kept on uninstall.
