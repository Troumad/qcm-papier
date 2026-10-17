"""Compte mail (SMTP) dédié : réglages enregistrés, mot de passe jamais stocké."""

import json
import os

import pytest

from qcm_papier import mail_config  # noqa: E402
from qcm_papier.mail_config import MailConfigError  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_compte_absent(cfg):
    account = mail_config.load_account()
    assert not account.complete


def test_enregistrement_sans_mot_de_passe(cfg):
    account = mail_config.save_account(
        "smtp.univ-lyon1.fr", "587", "prenom.nom@univ-lyon1.fr", "prenom.nom@univ-lyon1.fr", starttls=True
    )
    assert (account.host, account.port, account.username, account.sender) == (
        "smtp.univ-lyon1.fr",
        587,
        "prenom.nom@univ-lyon1.fr",
        "prenom.nom@univ-lyon1.fr",
    )
    assert account.complete
    content = (cfg / "mail.json").read_text()
    data = json.loads(content)
    assert data == {
        "host": "smtp.univ-lyon1.fr",
        "port": 587,
        "username": "prenom.nom@univ-lyon1.fr",
        "sender": "prenom.nom@univ-lyon1.fr",
        "starttls": True,
    }
    assert "password" not in content and "passwd" not in content
    if os.name != "nt":
        assert oct(os.stat(cfg / "mail.json").st_mode & 0o777) == "0o600"


def test_champs_manquants(cfg):
    with pytest.raises(MailConfigError, match="serveur"):
        mail_config.save_account("", "587", "prof", "sender")
    with pytest.raises(MailConfigError, match="Identifiant"):
        mail_config.save_account("smtp.univ.fr", "587", "", "sender")
    with pytest.raises(MailConfigError, match="expédition"):
        mail_config.save_account("smtp.univ.fr", "587", "prof", "")


def test_port_invalide(cfg):
    with pytest.raises(MailConfigError, match="Port"):
        mail_config.save_account("smtp.univ.fr", "abc", "prof", "sender")
    with pytest.raises(MailConfigError, match="Port"):
        mail_config.save_account("smtp.univ.fr", "99999", "prof", "sender")


def test_supprimer_le_compte(cfg):
    mail_config.save_account("smtp.univ.fr", "587", "prof", "prof@univ.fr")
    mail_config.delete_account()
    assert not (cfg / "mail.json").exists()
    assert not mail_config.load_account().complete
