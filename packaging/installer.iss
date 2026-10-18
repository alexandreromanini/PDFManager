; Inno Setup 6 - appele par build.ps1 : ISCC /DAppVersion=x.y.z packaging\installer.iss
; (fichier en UTF-8 avec BOM : sans BOM, ISCC le lirait en ANSI et abimerait les accents)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Modèle de l'assistant IA : mêmes valeurs que src/pdfmanager/services/assistant.py
#define AiFile "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
#define AiUrl "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/" + AiFile
#define AiSha256 "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
#define AiDir "{localappdata}\PDFManager\ai"

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
SetupIconFile=pdfmanager.ico
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "fileassoc"; Description: "Associer les fichiers .pdf (menu Ouvrir avec)"; Flags: unchecked
Name: "ai"; Description: "Assistant IA hors ligne : résumer un PDF, lui poser des questions (téléchargement de 2,5 Go, 8 Go de mémoire conseillés)"; Flags: unchecked

[Files]
Source: "..\dist\PDFManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Modèle IA téléchargé avant l'installation (voir [Code]) ; absent si déjà installé
Source: "{tmp}\{#AiFile}"; DestDir: "{#AiDir}"; Flags: external skipifsourcedoesntexist ignoreversion; Tasks: ai

[UninstallDelete]
; modèle installé ici ou téléchargé depuis l'application
Type: filesandordirs; Name: "{#AiDir}"

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
; Mise a jour lancee depuis l'application (installation silencieuse) : relance
Filename: "{app}\PDFManager.exe"; Flags: nowait postinstall skipifnotsilent

[Code]
var
  AiPage: TDownloadWizardPage;

procedure InitializeWizard;
begin
  AiPage := CreateDownloadPage('Assistant IA', 'Téléchargement du modèle (2,5 Go, une seule fois)…', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('ai')
     and not FileExists(ExpandConstant('{#AiDir}\{#AiFile}')) then begin
    AiPage.Clear;
    AiPage.Add('{#AiUrl}', '{#AiFile}', '{#AiSha256}');
    AiPage.Show;
    try
      try
        AiPage.Download;
      except
        // L'application s'installe quand même ; le modèle se télécharge aussi depuis elle.
        if not AiPage.AbortedByUser then
          SuppressibleMsgBox('Le modèle de l''assistant IA n''a pas pu être téléchargé : '
            + GetExceptionMessage + #13#10#13#10 + 'PDFManager s''installe sans lui ; '
            + 'il pourra être téléchargé depuis le panneau Assistant de l''application.',
            mbInformation, MB_OK, IDOK);
      end;
    finally
      AiPage.Hide;
    end;
  end;
end;
