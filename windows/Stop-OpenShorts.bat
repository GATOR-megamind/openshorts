@echo off
rem Stops the OpenShorts containers (clips in output\ are kept).
setlocal
cd /d "%~dp0.."
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.export.yml stop
