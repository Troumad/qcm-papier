#!/bin/sh
# Lanceur qcm-papier pour Linux (appelé par qcm-papier.desktop).
# Utilise l'environnement du projet (.venv) s'il existe, sinon le python3 du système.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m qcm_papier
fi
exec python3 -m qcm_papier
