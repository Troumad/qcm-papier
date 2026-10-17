"""Compte mail (SMTP) dédié : réglages enregistrés sur la machine.

- le serveur, le port, l'identifiant et l'expéditeur sont dans un petit fichier
  JSON du dossier de configuration de l'utilisateur (le même que ScoDoc) ;
- le mot de passe est rangé dans le **trousseau du système** (Trousseau macOS,
  Gestionnaire d'identifiants Windows, Secret Service sous Linux) via
  ``keyring``. Il n'est jamais écrit dans un fichier ni renvoyé par l'API web.
  Sans trousseau disponible, l'enregistrement est refusé.

Le dossier de configuration peut être changé avec ``QCM_PAPIER_CONFIG_DIR``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from .scodoc_api import ScoDocError

KEYRING_SERVICE = "qcm-papier-mail"
CONFIG_NAME = "mail.json"


class MailConfigError(ScoDocError):
    """Réglages absents ou trousseau indisponible."""


@dataclass
class MailAccount:
    host: str = ""
    port: int = 587
    username: str = ""
    sender: str = ""
    starttls: bool = True
    has_password: bool = False

    @property
    def complete(self) -> bool:
        return bool(self.host and self.username and self.sender and self.has_password)


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


def _keyring():
    try:
        import keyring
        from keyring.backends import chainer, fail, null
    except ImportError as e:
        raise MailConfigError('Module « keyring » absent : pip install -e ".[web]"') from e

    backend = keyring.get_keyring()
    candidates = backend.backends if isinstance(backend, chainer.ChainerBackend) else [backend]
    for candidate in candidates:
        if not isinstance(candidate, fail.Keyring | null.Keyring) and not type(candidate).__module__.startswith(
            "keyrings.alt"
        ):
            return candidate
    raise MailConfigError(
        "Aucun trousseau sécurisé disponible sur cette machine : le mot de passe ne peut pas être enregistré."
    )


def _password(method: str, username: str, *args):
    backend = _keyring()
    from keyring.errors import KeyringError

    try:
        return getattr(backend, method)(KEYRING_SERVICE, username, *args)
    except KeyringError as exc:
        raise MailConfigError("Le trousseau est inaccessible ou verrouillé. Déverrouillez-le puis réessayez.") from exc


def keyring_name() -> str:
    """Nom du trousseau utilisé (affiché dans les réglages)."""
    try:
        backend = _keyring()
    except MailConfigError as e:
        return str(e)
    return getattr(backend, "name", type(backend).__name__)


def load_account() -> MailAccount:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return MailAccount()
    if not isinstance(data, dict):
        raise MailConfigError("Le fichier de configuration mail est invalide.")
    username = str(data.get("username", ""))
    has_password = False
    if username:
        try:
            has_password = bool(_password("get_password", username))
        except MailConfigError:
            has_password = False
    return MailAccount(
        host=str(data.get("host", "")),
        port=int(data.get("port", 587) or 587),
        username=username,
        sender=str(data.get("sender", "")),
        starttls=bool(data.get("starttls", True)),
        has_password=has_password,
    )


def save_account(
    host: str, port: int, username: str, sender: str, password: str | None = None, starttls: bool = True
) -> MailAccount:
    """Enregistre le compte. ``password`` vide ou None : on garde celui du trousseau."""
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
    _keyring()
    previous = load_account()
    if password:
        _password("set_password", username, password)
    elif previous.host != host or previous.username != username or not previous.has_password:
        raise MailConfigError("Mot de passe requis pour ce compte.")
    if previous.username and previous.username != username:
        _delete_password(previous.username)
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


def _delete_password(username: str) -> None:
    from keyring.errors import KeyringError, PasswordDeleteError

    try:
        _keyring().delete_password(KEYRING_SERVICE, username)
    except PasswordDeleteError:
        pass
    except KeyringError as exc:
        raise MailConfigError("Impossible de supprimer le mot de passe du trousseau.") from exc


def delete_account() -> None:
    account = load_account()
    if account.username:
        _delete_password(account.username)
    try:
        os.remove(_config_path())
    except FileNotFoundError:
        pass


def smtp_password() -> str:
    """Mot de passe du compte enregistré (depuis le trousseau)."""
    account = load_account()
    if not account.username:
        raise MailConfigError("Compte mail non configuré : renseignez-le dans l'onglet Réglages.")
    password = _password("get_password", account.username)
    if not password:
        raise MailConfigError("Aucun mot de passe enregistré dans le trousseau.")
    return password
