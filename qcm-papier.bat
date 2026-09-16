@echo off
REM Lanceur qcm-papier (double-clic pour ouvrir l'interface graphique).
REM Placez ce .bat à côté du projet qcm-papier (le dossier contenant pyproject.toml)
REM ou adaptez CHEMIN_PROJET ci-dessous.
REM Utilise l'environnement du projet (.venv) s'il existe, sinon le pythonw du système.
setlocal
set "CHEMIN_PROJET=%~dp0"
cd /d "%CHEMIN_PROJET%"
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" -m qcm_papier
) else (
    pythonw -m qcm_papier
)
endlocal
