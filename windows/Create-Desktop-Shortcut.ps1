# Puts an "OpenShorts" shortcut on the desktop that runs OpenShorts.bat.
#   powershell -ExecutionPolicy Bypass -File windows\Create-Desktop-Shortcut.ps1
$launcher = Join-Path $PSScriptRoot "OpenShorts.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop "OpenShorts.lnk"))
$link.TargetPath = $launcher
$link.WorkingDirectory = $PSScriptRoot
$link.WindowStyle = 7  # minimized: the console only shows progress
$link.Save()
Write-Host "Shortcut created on the desktop: OpenShorts"
