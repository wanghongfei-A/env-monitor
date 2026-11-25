' Run backend hidden (no console window). Closing windows does NOT stop it.
' Log goes to logs\server.log
' Keep this file ASCII-only.
Dim fso, shell, base
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
shell.Run "cmd /c """ & base & "\scripts\run_server.bat""", 0, False
