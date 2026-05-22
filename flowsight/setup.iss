; =============================================================================
; FlowSight Installer — Inno Setup 6
; ใช้ Python Embedded + source .py โดยตรง ไม่ต้อง PyInstaller
; =============================================================================

#define AppName "FlowSight"
#define AppVersion "1.0"
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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; Flags: checkedonce
Name: "startup"; Description: "Auto-start with Windows"; Flags: unchecked

[Files]
; ── Python Embedded Runtime ──────────────────────────────────────────────────
Source: "installer\python_embedded\*"; DestDir: "{app}\python"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; ── FlowSight source files ───────────────────────────────────────────────────
Source: "server.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "app.py";             DestDir: "{app}"; Flags: ignoreversion
Source: "behavior_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "zones.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "tracker.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "dashboard.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "alert.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "logger.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "heatmap.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "report.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "report_pdf.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "ai_insight.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "license.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "activate.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "db_migrate.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "data_manager.py";    DestDir: "{app}"; Flags: ignoreversion

; ── Config files ─────────────────────────────────────────────────────────────
Source: "bytetrack.yaml";         DestDir: "{app}"; Flags: ignoreversion
Source: "brand_config.json";      DestDir: "{app}"; Flags: ignoreversion
Source: "behaviors_config.json";  DestDir: "{app}"; Flags: ignoreversion

; ── Templates and assets ─────────────────────────────────────────────────────
Source: "templates\*";  DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs
Source: "assets\*";     DestDir: "{app}\assets";    Flags: ignoreversion recursesubdirs

; ── Launcher scripts ──────────────────────────────────────────────────────────
Source: "installer\FlowSight.bat";        DestDir: "{app}"; Flags: ignoreversion
Source: "installer\install_packages.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FlowSight";          Filename: "{app}\FlowSight.bat"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Uninstall FlowSight"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FlowSight";     Filename: "{app}\FlowSight.bat"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\FlowSight";     Filename: "{app}\FlowSight.bat"; Tasks: startup

[Run]
; Install packages หลัง install เสร็จ
Filename: "{app}\install_packages.bat"; \
  Description: "Installing required packages (3-5 minutes)..."; \
  Flags: runhidden waituntilterminated

; เปิด FlowSight หลัง install
Filename: "{app}\FlowSight.bat"; \
  Description: "Launch FlowSight now"; \
  Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'FlowSight Retail Intelligence Platform' + #13#10#13#10 +
    'Python runtime and all components are included.' + #13#10 +
    'No additional software installation required.' + #13#10#13#10 +
    'First-time setup takes 3-5 minutes (internet required).' + #13#10 +
    'Please keep internet connection during installation.';
end;
