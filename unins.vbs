Option Explicit

Dim shell, regPaths, i

Set shell = CreateObject("WScript.Shell")

regPaths = Array( _
    "HKCU\Software\Classes\*\shell\Catbox\shell\001_upload_user\command", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\001_upload_user", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\002_upload_anon\command", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\002_upload_anon", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\003_edit_userhash\command", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\003_edit_userhash", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\004_history\command", _
    "HKCU\Software\Classes\*\shell\Catbox\shell\004_history", _
    "HKCU\Software\Classes\*\shell\Catbox\shell", _
    "HKCU\Software\Classes\*\shell\Catbox", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h\command", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h\command", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h\command", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h\command", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h", _
    "HKCU\Software\Classes\*\shell\Litterbox\shell", _
    "HKCU\Software\Classes\*\shell\Litterbox", _
    "HKCU\Software\CatboxUploader" _
)

For i = 0 To UBound(regPaths)
    On Error Resume Next
    shell.RegDelete regPaths(i) & "\"
    On Error GoTo 0
Next

MsgBox "Catbox & Litterbox context menu entries removed successfully.", vbInformation, "Cleanup Complete"
