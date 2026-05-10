' Diamond — one-click launcher (D32).
'
' Double-click this file to launch Diamond as a native desktop app.
' Or right-click -> Send to -> Desktop (create shortcut) for an icon
' on your desktop. Or right-click -> Pin to Start.
'
' Why VBS and not a .bat: VBS can call WScript.Shell.Run with the
' "show window" arg set to 0, which means truly no console flash —
' not even the brief cmd window blink you'd get from a .bat. The
' user only sees the Diamond window appear.
'
' Why pythonw.exe and not python.exe: pythonw is the GUI-mode Python
' interpreter (no console window allocated, ever). Same code, no
' terminal.
'
' Prereqs (one-time):
'   1. .venv at the repo root with the desktop deps installed
'      (`make install-desktop`).
'   2. The Next.js standalone tree built
'      (`python scripts/build_desktop.py`).
'
' If either is missing, the launcher loads, fails fast in the boot
' thread, and renders an error page inside its own window — you'll
' know what to fix.

Option Explicit

Dim sh, fso, scriptDir, pyw, target

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = scriptDir & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pyw) Then
    MsgBox "Couldn't find " & pyw & vbCrLf & vbCrLf & _
           "Run `make install-desktop` from the repo root first.", _
           vbCritical, "Diamond — venv missing"
    WScript.Quit 1
End If

' sh.CurrentDirectory makes diamond.desktop.paths.bundle_root resolve
' correctly when running from source mode.
sh.CurrentDirectory = scriptDir

' WScript.Shell.Run signature:
'   Run(command, windowStyle, waitOnReturn)
'   windowStyle 0 = hidden; waitOnReturn False = fire-and-forget
target = """" & pyw & """ -m diamond.desktop"
sh.Run target, 0, False
