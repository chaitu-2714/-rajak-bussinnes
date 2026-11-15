; BizPilot AI — Windows installer (Inno Setup 6)
; Build with:  iscc installer\bizpilot_installer.iss
; Requires the PyInstaller output in dist\BizPilotAI (run deployment\build_windows.py first).

#define AppName "BizPilot AI"
#define AppVersion "1.0.0"
#define AppPublisher "BizPilot AI"
#define AppExe "BizPilotAI.exe"
#define ProjectRoot ".."

[Setup]
AppId={{8C4B2F5E-3A7D-4E9B-9C61-BizPilotAI01}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\BizPilot AI
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#ProjectRoot}\dist\installer
OutputBaseFilename=BizPilotAI-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile={#ProjectRoot}\installer\installer_assets\LICENSE.txt
SetupIconFile={#ProjectRoot}\resources\icons\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "launchafterinstall"; Description: "Launch {#AppName} after installation"; GroupDescription: "Finish:"; Flags: checkedonce

[Files]
; Application binaries only. User data never lives here.
Source: "{#ProjectRoot}\dist\BizPilotAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent; Tasks: launchafterinstall

[UninstallDelete]
; Only the installation directory is touched. Business data lives in
; %LOCALAPPDATA%\BizPilotAI and documents in the user profile, and is kept.

[Code]
function InitializeSetup(): Boolean;
var
  ExistingVersion: String;
begin
  Result := True;
  { Refuse to install over a running instance. }
  if CheckForMutexes('BizPilotAI-SingleInstance') then
  begin
    MsgBox('BizPilot AI is already running. Close it and run the installer again.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    { Create the per-user data directories so the first launch is quick and
      predictable. Existing data is never overwritten. }
    DataDir := ExpandConstant('{localappdata}\BizPilotAI');
    if not DirExists(DataDir) then
      ForceDirectories(DataDir);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Response: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Business records are never deleted silently. }
    if MsgBox('Your business database and documents are kept in' + #13#10 +
              ExpandConstant('{localappdata}\BizPilotAI') + #13#10 + #13#10 +
              'Remove them as well? This permanently deletes all business records.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\BizPilotAI'), True, True, True);
    end;
  end;
end;
