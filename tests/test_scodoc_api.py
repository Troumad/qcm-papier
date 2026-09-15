"""Levée d'anonymat via l'API ScoDoc, avec un faux serveur ScoDoc local."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qcm_papier import scodoc_api
from qcm_papier.scodoc_api import ScoDocAuthError, ScoDocClient, ScoDocError

USER, PASSWORD, TOKEN = "prof", "secret", "jeton-123"
ETUDIANTS = [
    {"etudid": 101, "code_nip": "12504873", "nom": "DUPONT", "prenom": "Jean"},
    {"id": 102, "code_nip": "P7654321", "nom": "MARTIN", "nom_usuel": "MARTIN-DURAND", "prenom": "Marie"},
    {"etudid": 103, "code_nip": None, "nom": "SANS", "prenom": "Nip"},
]


class FakeScoDoc(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if self.path == "/ScoDoc/api/tokens" and self.headers.get("Authorization") == expected:
            self._send(200, {"token": TOKEN})
        else:
            self._send(401, {"message": "refusé"})

    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"message": "jeton"})
            return
        routes = {
            "/ScoDoc/api/departements": [{"acronym": "GEII", "description": "Génie électrique"}],
            "/ScoDoc/api/departement/GEII/formsemestres_courants": [
                {"id": 7, "titre_num": "BUT GEII semestre 1", "date_debut": "2026-09-01", "date_fin": "2027-01-31"}
            ],
            "/ScoDoc/api/formsemestre/7/etudiants": ETUDIANTS,
        }
        if self.path in routes:
            self._send(200, routes[self.path])
        else:
            self._send(404, {"message": "introuvable"})


@pytest.fixture(scope="module")
def scodoc_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeScoDoc)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_normalize_base_url():
    assert scodoc_api.normalize_base_url("https://scodoc.exemple.fr/") == "https://scodoc.exemple.fr/ScoDoc"
    assert scodoc_api.normalize_base_url("https://scodoc.exemple.fr/ScoDoc") == "https://scodoc.exemple.fr/ScoDoc"
    assert scodoc_api.normalize_base_url("http://localhost:5000") == "http://localhost:5000/ScoDoc"
    with pytest.raises(ScoDocError, match="https"):
        scodoc_api.normalize_base_url("http://scodoc.exemple.fr")
    with pytest.raises(ScoDocError):
        scodoc_api.normalize_base_url("scodoc.exemple.fr")


def test_client_jeton_et_lectures(scodoc_url):
    client = ScoDocClient(scodoc_url)
    with pytest.raises(ScoDocAuthError):
        client.departements()
    client.authenticate(USER, PASSWORD)
    assert client.token == TOKEN
    assert [scodoc_api.departement_view(d) for d in client.departements()] == [
        {"acronym": "GEII", "label": "GEII — Génie électrique"}
    ]
    sems = [scodoc_api.formsemestre_view(s) for s in client.formsemestres_courants("GEII")]
    assert sems == [{"id": 7, "label": "BUT GEII semestre 1 (2026-09-01 → 2027-01-31)"}]
    with pytest.raises(ScoDocError, match="introuvable"):
        client.formsemestre_etudiants(99)


def test_mauvais_mot_de_passe(scodoc_url):
    with pytest.raises(ScoDocAuthError):
        ScoDocClient(scodoc_url).authenticate(USER, "faux")


def test_serveur_injoignable():
    with pytest.raises(ScoDocError, match="joindre"):
        ScoDocClient("http://127.0.0.1:9").authenticate(USER, PASSWORD)


def _session_avec_pages(tmp_path):
    """Session avec deux pages corrigées (dont une dont le n° n'est pas dans ScoDoc)."""
    from qcm_papier import scanner
    from qcm_papier.web.session import MarkedPage, Session

    session = Session(work_dir=str(tmp_path))
    for student_id, note in (("p2504873", 12.0), ("p0000001", 8.0)):
        page = scanner.ScannedPage(student_id=student_id, variant_id=1, value=note, total=20.0, complete=True)
        page.matrix_inv = scanner.Matrix()
        session.pages.append(MarkedPage(page=page, file_name="copies.pdf"))
    return session


@pytest.fixture
def memory_keyring(tmp_path, monkeypatch):
    keyring = pytest.importorskip("keyring")
    from tests.test_scodoc_config import MemoryKeyring

    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path / "config"))
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_levee_anonymat_par_api_web(scodoc_url, tmp_path, memory_keyring):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from qcm_papier.web.server import create_app

    session = _session_avec_pages(tmp_path)
    client = TestClient(create_app(session), base_url="http://127.0.0.1")
    status = client.get("/api/scodoc/api/status").json()
    assert (status["connected"], status["configured"]) == (False, False)
    assert "Réglages" in client.post("/api/scodoc/api/login").json()["detail"]

    # Réglages : compte dédié, mot de passe dans le trousseau, jamais renvoyé
    saved = client.put("/api/settings/scodoc", json={"url": scodoc_url, "username": USER, "password": "faux"}).json()
    assert saved["complete"] is True and "password" not in saved
    assert client.post("/api/settings/scodoc/test").status_code == 400  # mauvais mot de passe
    client.put("/api/settings/scodoc", json={"url": scodoc_url, "username": USER, "password": PASSWORD})
    assert client.post("/api/settings/scodoc/test").json()["message"].startswith("Connexion réussie")
    assert PASSWORD not in client.get("/api/settings/scodoc").text

    login = client.post("/api/scodoc/api/login").json()
    assert login["connected"] is True
    assert login["departements"][0]["acronym"] == "GEII"
    assert PASSWORD not in str(vars(session.scodoc_client))  # seul le jeton est gardé
    sems = client.get("/api/scodoc/api/formsemestres", params={"departement": "GEII"}).json()
    data = client.post("/api/scodoc/api/students", json={"formsemestre_id": sems[0]["id"]}).json()
    assert data["message"] == "2 étudiant(s) chargé(s) depuis ScoDoc, 1 copie(s) identifiée(s)."
    results = data["results"]
    assert results[0]["student"] == "DUPONT Jean"
    assert results[1]["student"] == "p0000001"
    assert session.notes == {"101": 12.0, "p0000001": 8.0}  # export par EID après identification

    assert client.post("/api/scodoc/api/logout").json()["connected"] is False
    assert client.get("/api/scodoc/api/formsemestres", params={"departement": "GEII"}).status_code == 400
    assert client.delete("/api/settings/scodoc").json()["complete"] is False
    assert memory_keyring.store == {}


def test_commande_scodoc_dump(scodoc_url, tmp_path, memory_keyring, capsys):
    import json as _json

    from qcm_papier import cli, scodoc_config

    scodoc_config.save_account(scodoc_url, USER, PASSWORD)
    out = tmp_path / "dump"
    assert cli.main(["scodoc", "dump", "-o", str(out), "-d", "GEII"]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "departements.json", "formsemestre_7_etudiants.json", "formsemestres_courants_GEII.json",
    ]  # fmt: skip
    assert _json.loads((out / "formsemestre_7_etudiants.json").read_text())[0]["code_nip"] == "12504873"
    printed = capsys.readouterr().out
    assert "données personnelles" in printed and PASSWORD not in printed


def test_students_from_api_meme_regle_que_excel(scodoc_url):
    client = ScoDocClient(scodoc_url)
    client.authenticate(USER, PASSWORD)
    students = scodoc_api.students_from_api(client.formsemestre_etudiants(7))
    assert set(students) == {"p2504873", "p7654321"}  # sans NIP : ignoré
    assert (students["p2504873"].eid, students["p2504873"].name) == ("101", "DUPONT")
    assert (students["p7654321"].eid, students["p7654321"].name) == ("102", "MARTIN-DURAND")
