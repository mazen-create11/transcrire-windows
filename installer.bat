@echo off
chcp 65001 >nul
title Installation de Transcrire
cd /d "%~dp0"
echo.
echo   Installation de Transcrire
echo   ==========================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   Python n'est pas installe. Je le fais poser par Windows...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo   Impossible d'installer Python automatiquement.
    echo   Telecharge-le sur https://www.python.org/downloads/ puis relance ce fichier.
    pause
    exit /b 1
  )
  echo   Ferme cette fenetre et relance installer.bat.
  pause
  exit /b 0
)

echo   [1/3] Preparation de l'environnement...
python -m venv .venv || goto :rate
echo   [2/3] Telechargement des composants (quelques minutes la premiere fois)...
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\python -m pip install -r requirements.txt --quiet || goto :rate
echo   [3/3] Raccourci sur le Bureau...
powershell -NoProfile -Command ^
  "$b=(New-Object -ComObject WScript.Shell).SpecialFolders('Desktop');" ^
  "$r=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$b\Transcrire.lnk\");" ^
  "$r.TargetPath='%~dp0Transcrire.bat';$r.WorkingDirectory='%~dp0';$r.IconLocation='%SystemRoot%\System32\SndVol.exe,0';$r.Save()"

echo.
echo   C'est fait. Double-clique sur Transcrire (Bureau) pour demarrer.
echo.
pause
exit /b 0

:rate
echo.
echo   L'installation a echoue. Envoie-moi ce que tu vois au-dessus.
pause
exit /b 1
