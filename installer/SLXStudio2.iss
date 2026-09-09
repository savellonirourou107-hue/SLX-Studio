#define MyAppName "SLX Studio 2"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "SLX Studio contributors"
#define MyAppExeName "SLXStudio.exe"

[Setup]
AppId={{B90526D0-8A9C-4C45-8C3C-6F6CE1D4AA20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SLX Studio 2
DefaultGroupName=SLX Studio 2
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=SLX-Studio-2-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\release\SLXStudio-win32-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SLX Studio 2"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\SLX Studio 2"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SLX Studio 2"; Flags: nowait postinstall skipifsilent
