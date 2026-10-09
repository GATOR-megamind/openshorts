@echo off
rem OpenShorts launcher for Windows: starts Docker Desktop if needed, brings the
rem stack up (with the GPU override when an NVIDIA card is present) and opens
rem the dashboard in its own app window.
rem   OpenShorts.bat           start
rem   OpenShorts.bat update    rebuild the images first (after a git pull)
setlocal
cd /d "%~dp0.."

docker info >nul 2>&1
if errorlevel 1 (
    echo Starting Docker Desktop...
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    for /l %%i in (1,1,60) do (
        timeout /t 3 /nobreak >nul
        docker info >nul 2>&1 && goto docker_ready
    )
    echo Docker Desktop did not start. Open it by hand and run this again.
    pause
    exit /b 1
)
:docker_ready

rem Finished clips are copied to a "clips" folder on the desktop.
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "CLIPS_DIR=%%d\clips"
if not exist "%CLIPS_DIR%" mkdir "%CLIPS_DIR%"

set "COMPOSE=docker compose -f docker-compose.yml -f docker-compose.export.yml"
nvidia-smi >nul 2>&1 && set "COMPOSE=%COMPOSE% -f docker-compose.gpu.yml"

set "BUILD="
if /i "%~1"=="update" set "BUILD=--build"

echo Starting OpenShorts (the first run builds the images, that takes a while)...
%COMPOSE% up -d %BUILD%
if errorlevel 1 (
    echo Could not start OpenShorts. See the messages above.
    pause
    exit /b 1
)

echo Waiting for the backend...
for /l %%i in (1,1,120) do (
    curl -sf http://localhost:8000/health >nul 2>&1 && goto backend_ready
    timeout /t 2 /nobreak >nul
)
echo The backend is still starting; the window opens anyway.
:backend_ready

set "URL=http://localhost:5175"
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=%URL%
) else if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --app=%URL%
) else (
    start "" %URL%
)
