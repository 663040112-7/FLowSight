' =============================================================================
' FlowSight.vbs — Silent launcher (no CMD window)
' Place this file in the FlowSight install directory alongside app.py.
' Run via: wscript.exe FlowSight.vbs
' The desktop/Start Menu shortcuts point to wscript.exe with this file.
' =============================================================================
Option Explicit

Dim fso, appDir, pythonw, appPy, shell

Set fso    = CreateObject("Scripting.FileSystemObject")
appDir     = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw    = appDir & "\python\pythonw.exe"
appPy      = appDir & "\app.py"

' Verify bundled Python exists before attempting launch
If Not fso.FileExists(pythonw) Then
    MsgBox "Bundled Python not found." & vbCrLf & vbCrLf & _
           "Expected: " & pythonw & vbCrLf & vbCrLf & _
           "Please re-run the FlowSight installer.", _
           vbCritical, "FlowSight — Launch Error"
    WScript.Quit 1
End If

If Not fso.FileExists(appPy) Then
    MsgBox "Application file not found." & vbCrLf & vbCrLf & _
           "Expected: " & appPy & vbCrLf & vbCrLf & _
           "Please re-run the FlowSight installer.", _
           vbCritical, "FlowSight — Launch Error"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")

' Set environment variables for this process
Dim env
Set env = shell.Environment("Process")
env("PYTHONPATH")                       = appDir & "\python\Lib\site-packages"
env("KMP_DUPLICATE_LIB_OK")             = "TRUE"
env("OPENCV_LOG_LEVEL")                 = "SILENT"
env("OPENCV_FFMPEG_CAPTURE_OPTIONS")    = "rtsp_transport;tcp"

' Launch pythonw.exe (no console window) with app.py
' WindowStyle 0 = hidden, bWaitOnReturn False = fire and forget
Dim cmd
cmd = """" & pythonw & """ """ & appPy & """"
shell.Run cmd, 0, False

Set shell = Nothing
Set fso   = Nothing
