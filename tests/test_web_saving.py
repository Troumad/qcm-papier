"""Les sauvegardes valident un instantané, pas les modifications ultérieures."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from qcm_papier.web.server import create_app
from qcm_papier.web.session import Session


@pytest.fixture
def app(tmp_path):
    session = Session(work_dir=str(tmp_path))
    return TestClient(create_app(session), base_url="http://127.0.0.1:8060"), session


def test_projet_modifie_pendant_sauvegarde_reste_sale(app):
    client, _ = app
    assert not client.get("/api/work").json()["project_dirty"]
    client.put("/api/settings", json={"evaluation_short": "premier"})
    snapshot = client.get("/api/project/download")
    assert client.get("/api/work").json()["project_dirty"]  # Télécharger ne prouve pas l'écriture.
    client.put("/api/settings", json={"evaluation_short": "second"})
    result = client.post("/api/work/saved", json={"project_token": snapshot.headers["X-Project-Token"]})
    assert result.json()["project_dirty"]
    latest = client.get("/api/project/download")
    result = client.post("/api/work/saved", json={"project_token": latest.headers["X-Project-Token"]})
    assert not result.json()["project_dirty"]


def test_json_ne_valide_pas_la_correction(app):
    client, _ = app
    client.put("/api/correction/clair", json={"clair": 150})
    snapshot = client.get("/api/project/download")
    result = client.post("/api/work/saved", json={"project_token": snapshot.headers["X-Project-Token"]})
    assert result.json()["correction_dirty"]
    revision = result.json()["correction_token"]
    client.put("/api/correction/clair", json={"clair": 160})
    assert client.post("/api/work/saved", json={"correction_token": revision}).json()["correction_dirty"]
    revision = client.get("/api/work").json()["correction_token"]
    assert not client.post("/api/work/saved", json={"correction_token": revision}).json()["correction_dirty"]


@pytest.mark.parametrize("path", ["/api/project/new", "/api/state/load", "/api/scodoc/api/students"])
def test_remplacement_refuse_pendant_correction(app, path):
    client, session = app
    session.job.running = True
    assert client.post(path, json={}).status_code == 409
    assert client.get("/api/state/save").status_code == 409
    assert client.get("/api/generate/bundle").status_code == 409


def test_bundle_contient_pdf_et_projet_correspondant(app):
    client, _ = app
    client.post("/api/structure/exercises")
    client.put("/api/settings", json={"generate_variants": "42", "evaluation_short": "Examen"})
    client.post("/api/generate/variants")
    result = client.get("/api/generate/bundle")
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert set(archive.namelist()) == {"Examen.pdf", "Examen.json"}
        assert archive.read("Examen.pdf").startswith(b"%PDF")
        assert archive.read("Examen.json") == client.get("/api/project/download").content
    assert result.headers["X-Project-Token"] == client.get("/api/work").json()["project_token"]


def test_ouvrir_un_projet_efface_ancienne_correction(app):
    client, session = app
    content = client.get("/api/project/download").content
    session.add_copy("exemple.pdf", b"exemple")
    client.put("/api/correction/clair", json={"clair": 150})
    assert client.post("/api/project/open", files={"file": ("projet.json", content)}).status_code == 200
    assert not session.copies
    assert not client.get("/api/work").json()["correction_dirty"]
    assert not client.get("/api/work").json()["project_dirty"]


def test_archive_conserve_copies_en_attente_et_seuil(app, tmp_path, monkeypatch):
    import time

    client, session = app
    session.add_copy("a_corriger.pdf", b"copie non encore lue")
    client.put("/api/correction/clair", json={"clair": 175})
    archive = client.get("/api/state/save")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert zipped.read("copies/a_corriger.pdf") == b"copie non encore lue"
    restored_dir = tmp_path / "restaure"
    restored_dir.mkdir()
    restored = Session(work_dir=str(restored_dir))
    original_load = restored.start_load_state_zip

    def load_before_response(data):
        original_load(data)
        deadline = time.monotonic() + 5
        while restored.job.running:
            assert time.monotonic() < deadline
            time.sleep(0.01)

    # Une reprise rapide peut finir avant la réponse et son middleware.
    monkeypatch.setattr(restored, "start_load_state_zip", load_before_response)
    restored_client = TestClient(create_app(restored), base_url="http://127.0.0.1:8060")
    response = restored_client.post("/api/state/load", files={"file": ("correction.zip", archive.content)})
    assert response.status_code == 200
    assert not restored.job.error
    assert restored.clair == 175
    assert restored.copies[0].checked
    assert not restored.pages
    assert not restored.work_state()["correction_dirty"]


def test_archive_sans_copies_conserve_le_projet(app):
    client, _ = app
    client.put("/api/settings", json={"evaluation_short": "Mon examen"})
    snapshot = client.get("/api/state/save")
    assert snapshot.status_code == 200
    result = client.post(
        "/api/work/saved",
        json={
            "project_token": snapshot.headers["X-Project-Token"],
            "correction_token": int(snapshot.headers["X-Correction-Token"]),
        },
    ).json()
    assert not result["project_dirty"]
    assert not result["correction_dirty"]


def test_modification_ne_reexporte_pas_les_anciennes_variantes(app):
    import pymupdf

    client, _ = app
    client.post("/api/structure/exercises")
    client.patch("/api/structure/exercises/0", json={"name": "Ancien titre"})
    client.put("/api/settings", json={"generate_variants": "42"})
    client.post("/api/generate/variants")
    client.get("/api/generate/preview")
    client.patch("/api/structure/exercises/0", json={"name": "Nouveau titre"})
    snapshot = client.get("/api/project/download")
    assert snapshot.json()["structure"][0]["name"] == "Nouveau titre"
    assert snapshot.json()["web_variants_stale"]
    for route in ("pdf", "preview", "preview/0", "bundle"):
        response = client.get(f"/api/generate/{route}")
        assert response.status_code == 400
        assert "variantes" in response.json()["detail"]
    # Sauvegarder et rouvrir le brouillon ne doit pas masquer le problème.
    client.post("/api/project/open", files={"file": ("projet.json", snapshot.content)})
    assert client.get("/api/generate/pdf").status_code == 400
    assert client.post("/api/generate/variants").status_code == 200
    pdf = client.get("/api/generate/pdf")
    assert pdf.status_code == 200
    with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
    assert "Nouveau titre" in text
    assert "Ancien titre" not in text
    assert "web_variants_stale" not in client.get("/api/project/download").json()
