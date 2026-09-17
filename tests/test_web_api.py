"""API de l'interface web (FastAPI), sans navigateur."""

import io
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from qcm_papier.web.server import create_app  # noqa: E402
from qcm_papier.web.session import Session  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(REPO, "math", "2026", "correction3.pdf")
PROJECT = os.path.join(REPO, "math", "2026", "OML1_bis.json")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Session(work_dir=str(tmp_path))), base_url="http://127.0.0.1:8060")


def test_commandes_reservees_a_application_locale(client):
    assert client.get("/api/project").status_code == 200
    assert client.get("/api/project", headers={"host": "evil.example"}).status_code == 403
    for origin in ("https://evil.example", "null", "http://127.0.0.1:9999"):
        assert client.post("/api/project/new", headers={"origin": origin}).status_code == 403
    assert client.post("/api/project/new", headers={"origin": "http://127.0.0.1:8060"}).status_code == 200
    assert client.post("/api/project/new", headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_aide_du_paquet_installe(client, monkeypatch):
    from email.message import Message

    from qcm_papier.web import server

    installed_metadata = Message()
    installed_metadata.set_payload("# QCM-Papier — guide installé")
    monkeypatch.setattr(server, "_help_path", lambda: "")
    monkeypatch.setattr(server, "metadata", lambda _name: installed_metadata)
    assert "guide installé" in client.get("/api/help").text


def test_page_et_fichiers_statiques(client):
    assert "QCM-Papier" in client.get("/").text
    for name in ("app.js", "correction.js", "markdown.js", "settings.js", "style.css"):
        assert client.get(f"/static/{name}").status_code == 200
    assert "QCM-Papier" in client.get("/api/help").text


def test_edition_structure_et_parametres(client):
    data = client.post("/api/structure/exercises").json()
    assert data["structure"]["exercises"][0]["name"] == "Exercice 1"
    url = "/api/structure/exercises/0/questions/0"
    data = client.patch(url, json={"name": "Dérivée", "type": "multiple_exact"}).json()
    assert data["structure"]["exercises"][0]["questions"][0]["type"] == "multiple_exact"
    refused = client.put("/api/structure/exercises/0/questions/0/choices/0", json={"state": "neutral"}).json()
    assert refused["accepted"] is True  # choix multiples : autorisé
    assert client.put("/api/settings", json={"exercise_dir": "top"}).json()["settings"]["exercise_dir"] == "top"
    assert client.put("/api/settings", json={"exercise_dir": "diagonale"}).status_code == 400
    assert client.patch("/api/structure/exercises/9", json={"name": "x"}).status_code == 404


def test_suppression_et_deplacement_structure(client):
    for _ in range(2):
        client.post("/api/structure/exercises")
    client.patch("/api/structure/exercises/0", json={"name": "Premier"})
    client.patch("/api/structure/exercises/1", json={"name": "Second"})

    data = client.post("/api/structure/exercises/0/move", json={"delta": 1}).json()
    assert [e["name"] for e in data["structure"]["exercises"]] == ["Second", "Premier"]
    assert data["accepted"] is True
    assert client.post("/api/structure/exercises/0/move", json={"delta": -1}).json()["accepted"] is False

    client.post("/api/structure/exercises/0/questions")
    url = "/api/structure/exercises/0/questions"
    data = client.post(f"{url}/1/move", json={"delta": -1}).json()
    assert [q["name"] for q in data["structure"]["exercises"][0]["questions"]] == ["Question 2", "Question 1"]
    data = client.delete(f"{url}/0").json()
    assert [q["name"] for q in data["structure"]["exercises"][0]["questions"]] == ["Question 1"]
    assert client.delete(f"{url}/0").json()["accepted"] is False  # une question au minimum

    data = client.delete("/api/structure/exercises/1").json()
    assert [e["name"] for e in data["structure"]["exercises"]] == ["Second"]
    assert client.delete("/api/structure/exercises/0").json()["accepted"] is False  # un exercice au minimum


def test_structure_refuse_les_rangs_invalides(client):
    client.post("/api/structure/exercises")
    assert client.delete("/api/structure/exercises/9").status_code == 404
    assert client.delete("/api/structure/exercises/0/questions/9").status_code == 404
    assert client.post("/api/structure/exercises/9/move", json={"delta": 1}).status_code == 404
    assert client.post("/api/structure/exercises/0/move", json={"delta": 3}).status_code == 400


def test_generation_variantes_et_pdf(client):
    client.post("/api/structure/exercises")
    client.put("/api/settings", json={"generate_count": 2, "generate_variants": ""})
    data = client.post("/api/generate/variants").json()
    assert len(data["variants"]) == 2
    response = client.get("/api/generate/pdf")
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_apercu_du_sujet(client):
    client.post("/api/structure/exercises")
    assert client.get("/api/generate/preview").status_code == 400  # aucune variante

    client.put("/api/settings", json={"generate_count": 2, "generate_variants": ""})
    client.post("/api/generate/variants")
    data = client.get("/api/generate/preview").json()
    assert data["pages"] >= 1
    assert all(w > 0 and h > 0 for w, h in data["sizes"])

    image = client.get("/api/generate/preview/0", params={"dpi": 72})
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    grand = client.get("/api/generate/preview/0", params={"dpi": 150})
    assert len(grand.content) > len(image.content)

    assert client.get(f"/api/generate/preview/{data['pages']}").status_code == 404
    assert client.get("/api/generate/preview/0", params={"dpi": 5000}).status_code == 400


def test_apercu_sans_appel_prealable(client):
    """Une page demandée directement rend le sujet, sans passer par /preview."""
    client.post("/api/structure/exercises")
    client.put("/api/settings", json={"generate_count": 1, "generate_variants": ""})
    client.post("/api/generate/variants")
    assert client.get("/api/generate/preview/0").content.startswith(b"\x89PNG")


def test_ouverture_projet_et_telechargement(client):
    with open(PROJECT, "rb") as f:
        data = client.post("/api/project/open", files={"file": ("OML1_bis.json", f, "application/json")}).json()
    assert data["variants"]
    assert data["path"] is None
    assert client.post("/api/project/save").status_code == 400
    assert client.get("/api/project/download").json()["structure"]


@pytest.mark.skipif(not os.path.exists(PDF), reason="copies absentes")
def test_correction_complete(client):
    with open(PROJECT, "rb") as f:
        client.post("/api/project/open", files={"file": ("OML1_bis.json", f, "application/json")})
    with open(PDF, "rb") as f:
        client.post("/api/copies", files=[("files", ("correction3.pdf", f, "application/pdf"))])
    client.post("/api/correction/start")
    for _ in range(600):
        state = client.get("/api/correction").json()
        if not state["job"]["running"]:
            break
        time.sleep(0.1)
    assert state["job"]["error"] == ""
    assert [r["variant"] for r in state["results"]] == [497, 3152, 1240, 1680, 1752, 2672]
    assert client.get("/api/pages/0/image").content.startswith(b"\x89PNG")
    assert client.post("/api/pages/0/align", json={"points": [[0, 0]]}).status_code == 400
    info = client.post("/api/pages/3/student", json={"student_id": "p7654321"}).json()
    assert info["student_id"] == "p7654321"
    archive = client.get("/api/state/save")
    assert archive.headers["content-type"] == "application/zip"
    assert client.post("/api/copies/remove", json={"indices": [0]}).json()["results"] == []
    client.post("/api/state/load", files={"file": ("correction.zip", io.BytesIO(archive.content), "application/zip")})
    for _ in range(600):
        state = client.get("/api/correction").json()
        if not state["job"]["running"]:
            break
        time.sleep(0.1)
    assert len(state["results"]) == 6
