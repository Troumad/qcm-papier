"""Compte mail (SMTP) dédié : fichier de réglages + trousseau (factice en test)."""

import json
import os

import pytest

keyring = pytest.importorskip("keyring")

from keyring.backend import KeyringBackend  # noqa: E402

from qcm_papier import mail_config  # noqa: E402
from qcm_papier.mail_config import MailConfigError  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture
def ring(tmp_path, monkeypatch):
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_compte_absent(ring):
    account = mail_config.load_account()
    assert not account.complete
    with pytest.raises(MailConfigError, match="non configuré"):
        mail_config.smtp_password()


def test_mot_de_passe_dans_le_trousseau_pas_dans_le_fichier(ring, tmp_path):
    account = mail_config.save_account(
        "smtp.exemple.fr", "587", "prof@exemple.fr", "Prof Sender", "S3cret!", starttls=True
    )
    assert (account.host, account.port, account.username, account.has_password) == (
        "smtp.exemple.fr",
        587,
        "prof@exemple.fr",
        True,
    )
    content = (tmp_path / "mail.json").read_text()
    assert "S3cret!" not in content
    assert json.loads(content) == {
        "host": "smtp.exemple.fr",
        "port": 587,
        "username": "prof@exemple.fr",
        "sender": "Prof Sender",
        "starttls": True,
    }
    assert ring.store == {("qcm-papier-mail", "prof@exemple.fr"): "S3cret!"}
    if os.name != "nt":
        assert oct(os.stat(tmp_path / "mail.json").st_mode & 0o777) == "0o600"
    assert mail_config.smtp_password() == "S3cret!"


def test_champs_manquants(ring):
    with pytest.raises(MailConfigError, match="serveur"):
        mail_config.save_account("", "587", "prof", "sender", "x")
    with pytest.raises(MailConfigError, match="Identifiant"):
        mail_config.save_account("smtp.exemple.fr", "587", "", "sender", "x")
    with pytest.raises(MailConfigError, match="expédition"):
        mail_config.save_account("smtp.exemple.fr", "587", "prof", "", "x")


def test_port_invalide(ring):
    with pytest.raises(MailConfigError, match="Port"):
        mail_config.save_account("smtp.exemple.fr", "abc", "prof", "sender", "x")
    with pytest.raises(MailConfigError, match="Port"):
        mail_config.save_account("smtp.exemple.fr", "99999", "prof", "sender", "x")


def test_changer_de_serveur_exige_un_mot_de_passe(ring):
    mail_config.save_account("smtp.a.fr", "587", "prof", "Prof Sender", "S3cret!")
    with pytest.raises(MailConfigError, match="Mot de passe requis"):
        mail_config.save_account("smtp.b.fr", "587", "prof", "Prof Sender", "")
    account = mail_config.save_account("smtp.b.fr", "587", "prof", "Prof Sender", "AutreSecret")
    assert account.host == "smtp.b.fr" and account.has_password


def test_conserver_mot_de_passe_du_meme_compte(ring):
    mail_config.save_account("smtp.a.fr", "587", "prof", "Prof Sender", "secret")
    assert mail_config.save_account("smtp.a.fr", "587", "prof", "Prof Sender", "").has_password


def test_supprimer_le_compte(ring, tmp_path):
    mail_config.save_account("smtp.a.fr", "587", "prof", "Prof Sender", "x")
    mail_config.delete_account()
    assert ring.store == {}
    assert not (tmp_path / "mail.json").exists()
