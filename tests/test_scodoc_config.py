"""Compte ScoDoc dédié : fichier de réglages + trousseau (factice en test)."""

import json
import os

import pytest

keyring = pytest.importorskip("keyring")
from keyring.backend import KeyringBackend  # noqa: E402

from qcm_papier import scodoc_config  # noqa: E402
from qcm_papier.scodoc_config import ScoDocConfigError  # noqa: E402


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
        self.store.pop((service, username))


@pytest.fixture
def ring(tmp_path, monkeypatch):
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_compte_absent(ring):
    account = scodoc_config.load_account()
    assert not account.complete
    with pytest.raises(ScoDocConfigError, match="non configuré"):
        scodoc_config.connect()


def test_mot_de_passe_dans_le_trousseau_pas_dans_le_fichier(ring, tmp_path):
    account = scodoc_config.save_account("https://scodoc.exemple.fr", "api_stages", "S3cret!")
    assert (account.url, account.username, account.has_password) == (
        "https://scodoc.exemple.fr/ScoDoc",
        "api_stages",
        True,
    )
    content = (tmp_path / "scodoc.json").read_text()
    assert "S3cret!" not in content
    assert json.loads(content) == {"url": "https://scodoc.exemple.fr/ScoDoc", "username": "api_stages"}
    assert ring.store == {("qcm-papier-scodoc", "api_stages"): "S3cret!"}
    if os.name != "nt":
        assert oct(os.stat(tmp_path / "scodoc.json").st_mode & 0o777) == "0o600"


def test_changer_de_serveur_exige_un_mot_de_passe(ring):
    scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "api_stages", "S3cret!")
    with pytest.raises(ScoDocConfigError, match="Mot de passe requis"):
        scodoc_config.save_account("https://b.exemple.fr/ScoDoc", "api_stages", "")
    account = scodoc_config.save_account("https://b.exemple.fr/ScoDoc", "api_stages", "AutreSecret")
    assert account.url == "https://b.exemple.fr/ScoDoc" and account.has_password


def test_conserver_mot_de_passe_du_meme_compte(ring):
    scodoc_config.save_account("https://a.exemple.fr", "api_stages", "secret")
    assert scodoc_config.save_account("https://a.exemple.fr/", "api_stages", "").has_password


def test_changer_de_compte_exige_un_mot_de_passe_et_nettoie_l_ancien(ring):
    scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "ancien", "x")
    with pytest.raises(ScoDocConfigError, match="Mot de passe requis"):
        scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "nouveau", "")
    scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "nouveau", "y")
    assert ring.store == {("qcm-papier-scodoc", "nouveau"): "y"}


def test_supprimer_le_compte(ring, tmp_path):
    scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "api_stages", "x")
    scodoc_config.delete_account()
    assert ring.store == {}
    assert not (tmp_path / "scodoc.json").exists()


def test_adresse_http_refusee(ring):
    with pytest.raises(Exception, match="https"):
        scodoc_config.save_account("http://scodoc.exemple.fr", "api_stages", "x")


def test_sans_trousseau_on_refuse_d_enregistrer(tmp_path, monkeypatch):
    from keyring.backends import fail

    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        with pytest.raises(ScoDocConfigError, match="trousseau"):
            scodoc_config.save_account("https://a.exemple.fr/ScoDoc", "api_stages", "x")
        assert not (tmp_path / "scodoc.json").exists()
    finally:
        keyring.set_keyring(previous)


def test_backend_en_clair_refuse(ring, monkeypatch):
    monkeypatch.setattr(MemoryKeyring, "__module__", "keyrings.alt.file")
    with pytest.raises(ScoDocConfigError, match="trousseau sécurisé"):
        scodoc_config.save_account("https://a.exemple.fr", "compte", "secret")
    assert not ring.store


def test_trousseau_verrouille_erreur_affichable(ring, monkeypatch, tmp_path):
    from keyring.errors import KeyringError

    def locked(*_args):
        raise KeyringError("locked")

    monkeypatch.setattr(ring, "set_password", locked)
    with pytest.raises(ScoDocConfigError, match="verrouillé"):
        scodoc_config.save_account("https://a.exemple.fr", "compte", "secret")
    assert not (tmp_path / "scodoc.json").exists()
