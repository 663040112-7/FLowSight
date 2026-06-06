; =============================================================================
; FlowSight Installer — Inno Setup 6
; =============================================================================

#define AppName      "FlowSight"
#define AppVersion   "1.0"
#define AppPublisher "FlowSight"

[Setup]
AppId={{FLOWSIGHT-2026-A1B2C3D4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\FlowSight
DefaultGroupName={#AppName}
OutputDir=installer_output
OutputBaseFilename=FlowSight_Setup_v{#AppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; Flags: checkedonce
Name: "startup";     Description: "Auto-start with Windows";  Flags: unchecked

[Dirs]
Name: "{commonappdata}\FlowSight"; Permissions: users-modify

[Files]
; ── Python Embedded Runtime ──────────────────────────────────────────────────
Source: "installer\python_embedded\*"; DestDir: "{app}\python"; \
  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer\get-pip.py"; DestDir: "{app}\python"; Flags: ignoreversion

; ── FlowSight source files ────────────────────────────────────────────────────
Source: "app.py";             DestDir: "{app}"; Flags: ignoreversion
Source: "server.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "behavior_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "zones.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "zone_setup.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "tracker.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "detector.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "dashboard.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "alert.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "logger.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "heatmap.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "report.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "report_pdf.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "ai_insight.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "db_migrate.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "data_manager.py";    DestDir: "{app}"; Flags: ignoreversion
Source: "main.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "vendor_tools.py";    DestDir: "{app}"; Flags: ignoreversion

; ── Model and tracker config ──────────────────────────────────────────────────
Source: "bytetrack.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "yolov8n.pt";     DestDir: "{app}"; Flags: ignoreversion

; ── Writable configs → ProgramData ───────────────────────────────────────────
; Shipped default configs go to {app} as read-only templates.
; server.py seeds them into %PROGRAMDATA%\FlowSight on first run (writable),
; preserving any customised configs already present there.
Source: "brand_config.json";     DestDir: "{app}"; Flags: ignoreversion
Source: "behaviors_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "zones_config.json";     DestDir: "{app}"; Flags: ignoreversion

; ── UI assets ─────────────────────────────────────────────────────────────────
Source: "translations.js"; DestDir: "{app}"; Flags: ignoreversion
Source: "templates\*";     DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs
Source: "assets\*";        DestDir: "{app}\assets";    Flags: ignoreversion recursesubdirs

; ── Silent VBS launcher (replaces FlowSight.bat for no-CMD-window launch) ─────
Source: "installer\FlowSight.vbs"; DestDir: "{app}"; Flags: ignoreversion
; Keep .bat only as a debug fallback — not used by shortcuts
Source: "installer\FlowSight.bat";        DestDir: "{app}"; Flags: ignoreversion
Source: "installer\install_packages.bat"; DestDir: "{app}"; Flags: ignoreversion

; ── VC++ Redistributable ─────────────────────────────────────────────────────
Source: "installer\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
; All shortcuts use wscript.exe + FlowSight.vbs → completely silent launch
Name: "{group}\FlowSight"; \
  Filename: "{sys}\wscript.exe"; \
  Parameters: """{app}\FlowSight.vbs"""; \
  IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Uninstall FlowSight"; \
  Filename: "{uninstallexe}"
Name: "{autodesktop}\FlowSight"; \
  Filename: "{sys}\wscript.exe"; \
  Parameters: """{app}\FlowSight.vbs"""; \
  IconFilename: "{app}\assets\icon.ico"; \
  Tasks: desktopicon
Name: "{userstartup}\FlowSight"; \
  Filename: "{sys}\wscript.exe"; \
  Parameters: """{app}\FlowSight.vbs"""; \
  Tasks: startup

[Run]
; Step 1: VC++ runtime
Filename: "{tmp}\VC_redist.x64.exe"; \
  Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Installing Visual C++ Runtime..."; \
  Flags: waituntilterminated

; Step 2: Launch after install (uses VBS = no CMD window)
Filename: "{sys}\wscript.exe"; \
  Parameters: """{app}\FlowSight.vbs"""; \
  Description: "Launch FlowSight now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'FlowSight Retail Intelligence Platform' + #13#10#13#10 +
    'Python runtime and all components are included.' + #13#10 +
    'No additional software installation required.' + #13#10#13#10 +
    'First-time setup takes 3-5 minutes.' + #13#10 +
    'An internet connection is required to download Python packages.' + #13#10 +
    'Please keep the internet connection active during installation.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    Exec(ExpandConstant('{cmd}'),
         ExpandConstant('/c ""{app}\install_packages.bat""'),
         ExpandConstant('{app}'),
         SW_SHOW, ewWaitUntilTerminated, ResultCode);

    if ResultCode <> 0 then
    begin
      MsgBox(
        'Package installation returned an error (code ' + IntToStr(ResultCode) + ').' + #13#10#13#10 +
        'This usually means:' + #13#10 +
        '  - No internet connection during install' + #13#10 +
        '  - A firewall or proxy blocked the download' + #13#10 +
        '  - Insufficient disk space (need ~3 GB free)' + #13#10#13#10 +
        'FlowSight may not start correctly.' + #13#10 +
        'To retry: run install_packages.bat from the install folder.',
        mbError, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Answer: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if DirExists(ExpandConstant('{commonappdata}\FlowSight')) then
    begin
      Answer := MsgBox(
        'Do you want to delete FlowSight customer data?' + #13#10#13#10 +
        'This includes the analytics database, zone layouts, and' + #13#10 +
        'camera settings stored in:' + #13#10 +
        ExpandConstant('{commonappdata}\FlowSight') + #13#10#13#10 +
        'Click YES to fully remove all data (recommended).' + #13#10 +
        'Click NO to keep your data for a future reinstall.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON1);

      if Answer = IDYES then
        DelTree(ExpandConstant('{commonappdata}\FlowSight'), True, True, True);
    end;
  end;
end;
