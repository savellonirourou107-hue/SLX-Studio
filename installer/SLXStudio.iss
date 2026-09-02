#define MyAppName "SLX Studio"
#define MyAppVersion "1.0.0-beta.2"
#define MyAppPublisher "SLX Studio contributors"
#define MyAppExeName "SLXStudio.exe"

[Setup]
AppId={{F5D4D11D-4ED0-40B6-B345-CFB4108B37CB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SLX Studio
DefaultGroupName=SLX Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=SLX-Studio-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "assocm"; Description: "Add SLX Studio to Open with for MATLAB .m files"; GroupDescription: "Optional file integrations:"; Flags: unchecked
Name: "assocslx"; Description: "Add SLX Studio to Open with for Simulink .slx files"; GroupDescription: "Optional file integrations:"; Flags: unchecked

[Files]
Source: "..\dist\SLXStudio.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SLX Studio"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\SLX Studio"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\SLXStudio.MFile"; ValueType: string; ValueName: ""; ValueData: "MATLAB Script"; Tasks: assocm; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SLXStudio.MFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: assocm
Root: HKCU; Subkey: "Software\Classes\SLXStudio.MFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assocm
Root: HKCU; Subkey: "Software\Classes\.m\OpenWithProgids"; ValueType: string; ValueName: "SLXStudio.MFile"; ValueData: ""; Tasks: assocm; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SLXStudio.SLXFile"; ValueType: string; ValueName: ""; ValueData: "Simulink Model"; Tasks: assocslx; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SLXStudio.SLXFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: assocslx
Root: HKCU; Subkey: "Software\Classes\SLXStudio.SLXFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assocslx
Root: HKCU; Subkey: "Software\Classes\.slx\OpenWithProgids"; ValueType: string; ValueName: "SLXStudio.SLXFile"; ValueData: ""; Tasks: assocslx; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SLX Studio"; Flags: nowait postinstall skipifsilent
