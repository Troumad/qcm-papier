"""Compte mail (SMTP) dédié : réglages enregistrés sur la machine.

- le serveur, le port, l'identifiant et l'expéditeur sont dans un petit fichier
  JSON du dossier de configuration de l'utilisateur (le même que ScoDoc) ;
- le mot de passe n'est **jamais stocké** : il est saisi (en mode masqué)
  à chaque envoi des copies et ne quitte pas la session en cours.

Le dossier de configuration peut être changé avec ``QCM_PAPIER_CONFIG_DIR``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from .scodoc_api import ScoDocError

CONFIG_NAME = "mail.json"


class MailConfigError(ScoDocError):
    """Réglages absents ou invalides."""


@dataclass
class MailAccount:
    host: str = ""
    port: int = 587
    username: str = ""
    sender: str = ""
    starttls: bool = True

    @property
    def complete(self) -> bool:
        return bool(self.host and self.username and self.sender)


def config_dir() -> str:
    if os.environ.get("QCM_PAPIER_CONFIG_DIR"):
        return os.environ["QCM_PAPIER_CONFIG_DIR"]
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "qcm-papier")


def _config_path() -> str:
    return os.path.join(config_dir(), CONFIG_NAME)


def load_account() -> MailAccount:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return MailAccount()
    if not isinstance(data, dict):
        raise MailConfigError("Le fichier de configuration mail est invalide.")
    return MailAccount(
        host=str(data.get("host", "")),
        port=int(data.get("port", 587) or 587),
        username=str(data.get("username", "")),
        sender=str(data.get("sender", "")),
        starttls=bool(data.get("starttls", True)),
    )


def save_account(host: str, port: int, username: str, sender: str, starttls: bool = True) -> MailAccount:
    """Enregistre les réglages du compte. Le mot de passe n'est jamais stocké."""
    host = (host or "").strip()
    username = (username or "").strip()
    sender = (sender or "").strip()
    if not host:
        raise MailConfigError("Adresse du serveur SMTP requise.")
    if not username:
        raise MailConfigError("Identifiant requis.")
    if not sender:
        raise MailConfigError("Adresse d'expédition requise.")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise MailConfigError("Port invalide : nombre attendu.") from exc
    if not (1 <= port <= 65535):
        raise MailConfigError("Port invalide : il doit être entre 1 et 65535.")
    os.makedirs(config_dir(), exist_ok=True)
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"host": host, "port": port, "username": username, "sender": sender, "starttls": starttls},
            f,
            ensure_ascii=False,
            indent=2,
        )
    if os.name != "nt":
        os.chmod(path, 0o600)
    return load_account()


def delete_account() -> None:
    try:
        os.remove(_config_path())
    except FileNotFoundError:
        pass
