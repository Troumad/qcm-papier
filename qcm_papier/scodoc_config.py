"""Compte ScoDoc dédié : réglages enregistrés sur la machine.

- l'adresse du serveur et l'identifiant sont dans un petit fichier JSON du
  dossier de configuration de l'utilisateur ;
- le mot de passe est rangé dans le **trousseau du système** (Trousseau macOS,
  Gestionnaire d'identifiants Windows, Secret Service sous Linux) via
  ``keyring``. Il n'est jamais écrit dans un fichier ni renvoyé par l'API
  web. Sans trousseau disponible, l'enregistrement est refusé.

Le dossier de configuration peut être changé avec ``QCM_PAPIER_CONFIG_DIR``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from .scodoc_api import ScoDocClient, ScoDocError, normalize_base_url

KEYRING_SERVICE = "qcm-papier-scodoc"
CONFIG_NAME = "scodoc.json"


class ScoDocConfigError(ScoDocError):
    """Réglages absents ou trousseau indisponible."""


@dataclass
class ScoDocAccount:
    url: str = ""
    username: str = ""
    has_password: bool = False

    @property
    def complete(self) -> bool:
        return bool(self.url and self.username and self.has_password)


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
        raise ScoDocConfigError('Module « keyring » absent : pip install -e ".[web]"') from e
    backend = keyring.get_keyring()
    candidates = backend.backends if isinstance(backend, chainer.ChainerBackend) else [backend]
    for candidate in candidates:
        if not isinstance(candidate, fail.Keyring | null.Keyring) and not type(candidate).__module__.startswith(
            "keyrings.alt"
        ):
            return candidate
    raise ScoDocConfigError(
        "Aucun trousseau sécurisé disponible sur cette machine : le mot de passe ne peut pas être enregistré."
    )


def _password(method: str, username: str, *args):
    backend = _keyring()
    from keyring.errors import KeyringError

    try:
        return getattr(backend, method)(KEYRING_SERVICE, username, *args)
    except KeyringError as exc:
        raise ScoDocConfigError(
            "Le trousseau est inaccessible ou verrouillé. Déverrouillez-le puis réessayez."
        ) from exc


def keyring_name() -> str:
    """Nom du trousseau utilisé (affiché dans les réglages)."""
    try:
        backend = _keyring()
    except ScoDocConfigError as e:
        return str(e)
    return getattr(backend, "name", type(backend).__name__)


def load_account() -> ScoDocAccount:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ScoDocAccount()
    if not isinstance(data, dict):
        raise ScoDocConfigError("Le fichier de configuration ScoDoc est invalide.")
    url, username = str(data.get("url", "")), str(data.get("username", ""))
    has_password = False
    if username:
        try:
            has_password = bool(_password("get_password", username))
        except ScoDocConfigError:
            has_password = False
    return ScoDocAccount(url=url, username=username, has_password=has_password)


def save_account(url: str, username: str, password: str | None = None) -> ScoDocAccount:
    """Enregistre le compte. ``password`` vide ou None : on garde celui du trousseau."""
    url = normalize_base_url(url)
    username = (username or "").strip()
    if not username:
        raise ScoDocConfigError("Identifiant ScoDoc requis.")
    _keyring()
    previous = load_account()
    if password:
        _password("set_password", username, password)
    elif previous.url != url or previous.username != username or not previous.has_password:
        raise ScoDocConfigError("Mot de passe requis pour ce compte.")
    if previous.username and previous.username != username:
        _delete_password(previous.username)
    os.makedirs(config_dir(), exist_ok=True)
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"url": url, "username": username}, f, ensure_ascii=False, indent=2)
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
        raise ScoDocConfigError("Impossible de supprimer le mot de passe du trousseau.") from exc


def delete_account() -> None:
    account = load_account()
    if account.username:
        _delete_password(account.username)
    try:
        os.remove(_config_path())
    except FileNotFoundError:
        pass


def connect() -> ScoDocClient:
    """Client ScoDoc authentifié avec le compte enregistré."""
    account = load_account()
    if not account.complete:
        raise ScoDocConfigError("Compte ScoDoc non configuré : renseignez-le dans l'onglet Réglages.")
    password = _password("get_password", account.username)
    client = ScoDocClient(account.url)
    client.authenticate(account.username, password or "")
    return client
