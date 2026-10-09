# Puts a "clips" shortcut on the desktop pointing at the clips folder (once).
#   powershell -ExecutionPolicy Bypass -File windows\Create-Clips-Shortcut.ps1 C:\Users\me\clips
param([Parameter(Mandatory = $true)][string]$Target)
$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop "clips.lnk"
if (Test-Path $path) { exit 0 }
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
$link.TargetPath = $Target
$link.Save()
