; =============================================================================
; FlowSight Installer — Inno Setup Script
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
; Python Embedded
Source: "installer\python_embedded\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs

; App source files
Source: "server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "behavior_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "zones.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "tracker.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "dashboard.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "alert.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "logger.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "heatmap.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "report.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "report_pdf.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "ai_insight.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "license.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "activate.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "db_migrate.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "data_manager.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "bytetrack.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "brand_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "behaviors_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs

; Launcher
Source: "installer\FlowSight.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer\install_packages.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FlowSight"; Filename: "{app}\FlowSight.bat"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Uninstall FlowSight"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FlowSight"; Filename: "{app}\FlowSight.bat"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\FlowSight"; Filename: "{app}\FlowSight.bat"; Tasks: startup

[Run]
Filename: "{app}\install_packages.bat"; Description: "Installing packages..."; Flags: runhidden waituntilterminated
Filename: "{app}\FlowSight.bat"; Description: "Launch FlowSight"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'FlowSight Retail Intelligence Platform' + #13#10#13#10 +
    'This installer includes Python runtime and all components.' + #13#10 +
    'No additional software required.' + #13#10#13#10 +
    'First-time setup: 3-5 minutes (requires internet).' + #13#10 +
    'Please keep internet connection during installation.';
end;
