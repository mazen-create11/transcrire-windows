@echo off
chcp 65001 >nul
title Transcrire
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo   Lance d'abord installer.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m transcrire %*
