"""Persistance du projet au format JSON.

Reproduit ``ProjectSaveURL`` / ``ProjectModalLoad`` du code JavaScript original
(index.html lignes ~4980-5120) : le projet est sérialisé en
``{settings, variants, structure}`` (et ``students`` en extension). Les nombres
sont arrondis à 1 décimale (``Math.round(10*value)/10`` du code original) pour
rester compatible avec les fichiers existants.
"""

from __future__ import annotations

import json
from typing import Any, IO

from .model import Project


def _round_numbers(obj: Any) -> Any:
    """Arrondit récursivement les floats à 1 décimale.

    Reprend le ``JSON.stringify`` avec replacer ``Math.round(10*value)/10``
    (index.html ~5120). Les entiers sont préservés.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj * 10) / 10
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        return {k: _round_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_numbers(v) for v in obj]
    return obj


def project_to_json(project: Project, *, indent: int | None = 2) -> str:
    """Sérialise un projet en chaîne JSON compatible avec le format original."""
    data = project.to_dict()
    data = _round_numbers(data)
    return json.dumps(data, indent=indent, ensure_ascii=False)


def save_project(project: Project, path: str | IO[str], *,
                 indent: int | None = 2) -> None:
    """Sauvegarde un projet dans un fichier (ou objet fichier texte)."""
    content = project_to_json(project, indent=indent)
    if isinstance(path, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        path.write(content)


def load_project(path: str | IO[str] | dict) -> Project:
    """Charge un projet depuis un fichier JSON, une chaîne ou un dict.

    Accepte aussi directement un dict (pour les tests). Le format attendu est
    celui produit par le code original : ``{settings, variants, structure}``.
    """
    if isinstance(path, dict):
        data = path
    elif isinstance(path, str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(path)
    return Project.from_dict(data)


def project_to_url_data(project: Project) -> str:
    """Renvoie le contenu JSON brut (pour compatibilité avec une « data URL »)."""
    return project_to_json(project, indent=None)
