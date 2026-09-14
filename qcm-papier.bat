@echo off
REM Lanceur qcm-papier (double-clic pour ouvrir l'interface graphique).
REM Placez ce .bat à côté du projet qcm-papier (le dossier contenant pyproject.toml)
REM ou adaptez CHEMIN_PROJET ci-dessous.
setlocal
set "CHEMIN_PROJET=%~dp0"
cd /d "%CHEMIN_PROJET%"
pythonw -m qcm_papier
endlocal
