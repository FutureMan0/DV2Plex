; Inno Setup script for the DV2Plex desktop app. packaging/build.py runs it:
;   iscc /DMyAppVersion=2.0.0 packaging\windows\dv2plex.iss
; Installs per user (no administrator rights needed), with a start menu entry.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0D7A51-3F1C-4C9E-9C62-1D2E3F4A5B6C}
AppName=DV2Plex
AppVersion={#MyAppVersion}
AppVerName=DV2Plex {#MyAppVersion}
AppPublisher=DV2Plex contributors
AppPublisherURL=https://github.com/FutureMan0/DV2Plex
AppSupportURL=https://github.com/FutureMan0/DV2Plex/issues
AppUpdatesURL=https://github.com/FutureMan0/DV2Plex/releases
DefaultDirName={autopf}\DV2Plex
DefaultGroupName=DV2Plex
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=DV2Plex-{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\..\build\icons\icon.ico
UninstallDisplayIcon={app}\DV2Plex.exe
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\DV2Plex\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\DV2Plex"; Filename: "{app}\DV2Plex.exe"
Name: "{group}\DV2Plex (demo without a camera)"; Filename: "{app}\DV2Plex.exe"; Parameters: "--demo"
Name: "{group}\{cm:UninstallProgram,DV2Plex}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\DV2Plex"; Filename: "{app}\DV2Plex.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DV2Plex.exe"; Description: "{cm:LaunchProgram,DV2Plex}"; Flags: nowait postinstall skipifsilent
