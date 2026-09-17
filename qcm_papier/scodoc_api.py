"""Client minimal de l'API ScoDoc 9, pour la levée d'anonymat.

Évite de passer par le fichier Excel de la table des étudiants : on se connecte
au serveur ScoDoc, on choisit le semestre et on récupère directement les
étudiants (NIP, etudid, nom, prénom).

Authentification (https://scodoc.org/ScoDoc9API/) :

1. ``POST {base}/api/tokens`` avec l'identifiant et le mot de passe (Basic)
   renvoie ``{"token": "..."}`` ;
2. les requêtes suivantes envoient ``Authorization: Bearer <token>``.

Le mot de passe n'est utilisé que pour obtenir le jeton : il n'est ni gardé
ni enregistré. Seule la bibliothèque standard est utilisée.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .model import Student
from .scodoc import make_student

TIMEOUT = 30


class ScoDocError(Exception):
    """Erreur de communication avec ScoDoc (message affichable)."""


class ScoDocAuthError(ScoDocError):
    """Identifiants refusés ou session expirée."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ScoDocError("Redirection ScoDoc refusée : renseignez l'adresse finale du serveur.")


def normalize_base_url(url: str) -> str:
    """Nettoie l'adresse saisie : ``https://scodoc.exemple.fr`` → ``.../ScoDoc``.

    Refuse ``http://`` (le mot de passe circulerait en clair), sauf pour la
    machine locale.
    """
    url = (url or "").strip().rstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port  # Cette propriété valide le port et peut lever ValueError.
    except ValueError as exc:
        raise ScoDocError("Adresse ScoDoc invalide.") from exc
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ScoDocError("Adresse ScoDoc invalide (exemple : https://scodoc.exemple.fr/ScoDoc).")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ScoDocError("L'adresse ScoDoc ne doit contenir ni identifiants, ni paramètres, ni fragment.")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ScoDocError("Adresse en http:// refusée : utilisez https:// pour protéger le mot de passe.")
    if not parts.path:
        url += "/ScoDoc"
    return url


class ScoDocClient:
    """Accès en lecture à l'API ScoDoc avec un jeton."""

    def __init__(self, base_url: str):
        self.base_url = normalize_base_url(base_url)
        self.token: str | None = None

    def _open(self, request: urllib.request.Request) -> Any:
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ScoDocAuthError("Accès refusé par ScoDoc (identifiants ou droits insuffisants).") from e
            if e.code == 404:
                raise ScoDocError(f"Ressource introuvable sur ScoDoc : {request.full_url}") from e
            raise ScoDocError(f"Erreur ScoDoc : HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise ScoDocError(f"Impossible de joindre ScoDoc : {e.reason}") from e
        except (TimeoutError, json.JSONDecodeError) as e:
            raise ScoDocError(f"Réponse ScoDoc invalide ou trop lente : {e}") from e

    def authenticate(self, username: str, password: str) -> None:
        self.token = None
        if not username or not password:
            raise ScoDocAuthError("Identifiant et mot de passe ScoDoc requis.")
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        request = urllib.request.Request(
            f"{self.base_url}/api/tokens", method="POST", headers={"Authorization": f"Basic {credentials}"}
        )
        data = self._open(request)
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise ScoDocAuthError("ScoDoc n'a pas renvoyé de jeton d'accès.")
        self.token = token

    def get(self, endpoint: str) -> Any:
        if not self.token:
            raise ScoDocAuthError("Non connecté à ScoDoc.")
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}", headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            result = self._open(request)
        except ScoDocAuthError:
            self.token = None
            raise
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise ScoDocError("Réponse ScoDoc invalide : une liste d'objets était attendue.")
        return result

    def departements(self) -> list[dict]:
        return self.get("/api/departements")

    def formsemestres_courants(self, departement: str) -> list[dict]:
        acronym = urllib.parse.quote(departement, safe="")
        return self.get(f"/api/departement/{acronym}/formsemestres_courants")

    def formsemestre_etudiants(self, formsemestre_id: int) -> list[dict]:
        return self.get(f"/api/formsemestre/{int(formsemestre_id)}/etudiants")


def departement_view(dept: dict) -> dict[str, str]:
    acronym = str(dept.get("acronym") or dept.get("acronyme") or "")
    label = dept.get("description") or dept.get("dept_name") or acronym
    return {"acronym": acronym, "label": f"{acronym} — {label}" if label != acronym else acronym}


def formsemestre_view(sem: dict) -> dict[str, Any]:
    sem_id = sem.get("id") or sem.get("formsemestre_id")
    title = sem.get("titre_num") or sem.get("titre") or f"Semestre {sem_id}"
    dates = " → ".join(d for d in (sem.get("date_debut"), sem.get("date_fin")) if d)
    return {"id": int(sem_id), "label": f"{title} ({dates})" if dates else str(title)}


def students_from_api(etudiants: list[dict]) -> dict[str, Student]:
    """Table ``students`` (même forme que l'import Excel) à partir de l'API."""
    students: dict[str, Student] = {}
    for etud in etudiants:
        student = make_student(
            eid=etud.get("etudid") if etud.get("etudid") is not None else etud.get("id"),
            nip=etud.get("code_nip"),
            name=etud.get("nom_usuel") or etud.get("nom"),
            firstname=etud.get("prenom"),
        )
        if student is not None:
            students[student.id] = student
    return students
