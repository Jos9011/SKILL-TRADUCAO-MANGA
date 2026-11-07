Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath

pythonwExe = "C:\Users\ja329\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
If Not fso.FileExists(pythonwExe) Then
    pythonwExe = "pythonw.exe"
End If

launcherScript = Chr(34) & strPath & "\studio\app_launcher.py" & Chr(34)
WshShell.Run Chr(34) & pythonwExe & Chr(34) & " " & launcherScript, 0, False
