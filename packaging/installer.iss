; Inno Setup 6 - appele par build.ps1 : ISCC /DAppVersion=x.y.z packaging\installer.iss
; (fichier sans accents : ISCC lit les .iss sans BOM en ANSI)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4D2A-9C1F-3E5B7A9D2C40}
AppName=PDFManager
AppVersion={#AppVersion}
AppPublisher=PDFManager
DefaultDirName={autopf}\PDFManager
DisableProgramGroupPage=yes
; Installation par utilisateur sans droits admin, avec choix "pour tous" possible.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=PDFManager-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
ChangesAssociations=yes
UninstallDisplayIcon={app}\PDFManager.exe
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "fileassoc"; Description: "Associer les fichiers .pdf (menu Ouvrir avec)"; Flags: unchecked

[Files]
Source: "..\dist\PDFManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PDFManager"; Filename: "{app}\PDFManager.exe"
Name: "{autodesktop}\PDFManager"; Filename: "{app}\PDFManager.exe"; Tasks: desktopicon

[Registry]
; Windows 11 interdit de s'imposer comme lecteur par defaut : on s'enregistre comme
; candidat, l'utilisateur choisit ensuite dans "Ouvrir avec" > "Toujours".
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFManager.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\PDFManager.Document"; ValueType: string; ValueName: ""; ValueData: "Document PDF"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\PDFManager.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PDFManager.exe,0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\PDFManager.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFManager.exe"" ""%1"""; Tasks: fileassoc

[Run]
Filename: "{app}\PDFManager.exe"; Description: "{cm:LaunchProgram,PDFManager}"; Flags: nowait postinstall skipifsilent
