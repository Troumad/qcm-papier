"""Correction, images et reprise ZIP avec un sujet synthétique public."""

import csv
import time
from pathlib import Path

from fastapi.testclient import TestClient

from qcm_papier import cli
from qcm_papier.web.server import create_app
from qcm_papier.web.session import Session


def wait(client):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = client.get("/api/correction").json()
        if not state["job"]["running"]:
            assert state["job"]["error"] == ""
            return state
        time.sleep(0.05)
    raise AssertionError("Correction trop longue")


def test_variante_manuelle_api(project_path, tmp_path):
    """Forcer une variante sur une page alignée relance la correction."""
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    (tmp_path / "session2").mkdir()
    session = Session(work_dir=str(tmp_path / "session2"))
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        assert (
            client.post(
                "/api/project/open", files={"file": ("projet.json", Path(project_path).read_bytes())}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/copies", files=[("files", ("sujet.pdf", pdf.read_bytes(), "application/pdf"))]
            ).status_code
            == 200
        )
        assert client.post("/api/correction/start").status_code == 200
        wait(client)
        # La copie (le sujet lui-même) est alignée : on force la variante 42.
        response = client.post("/api/pages/0/variant", json={"variant_id": "42"})
        assert response.status_code == 200
        assert response.json()["variant"] == 42
        assert response.json()["note"] == -1  # malus de 1 (n° étudiant illisible)
        # Variante inconnue : refusée avec un message d'erreur.
        response = client.post("/api/pages/0/variant", json={"variant_id": "999999"})
        assert response.status_code != 200


def test_malus_api(project_path, tmp_path):
    """Le malus est exposé, modifiable, et survit à la sauvegarde/reprise."""
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    (tmp_path / "session3").mkdir()
    session = Session(work_dir=str(tmp_path / "session3"))
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        client.post("/api/project/open", files={"file": ("projet.json", Path(project_path).read_bytes())})
        client.post("/api/copies", files=[("files", ("sujet.pdf", pdf.read_bytes(), "application/pdf"))])
        client.post("/api/correction/start")
        wait(client)
        info = client.get("/api/pages/0").json()
        # Sujet vierge : n° étudiant illisible -> malus automatique à 1.
        assert info["malus"] == 1
        response = client.post("/api/pages/0/malus", json={"malus": 2})
        assert response.json()["malus"] == 2
        archive = client.get("/api/state/save")
        client.post("/api/state/load", files={"file": ("correction.zip", archive.content)})
        wait(client)
        assert client.get("/api/pages/0").json()["malus"] == 2


def test_correction_images_et_reprise_api(project_path, tmp_path):
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    (tmp_path / "session").mkdir()
    session = Session(work_dir=str(tmp_path / "session"))
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        assert (
            client.post(
                "/api/project/open", files={"file": ("projet.json", Path(project_path).read_bytes())}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/copies", files=[("files", ("sujet.pdf", pdf.read_bytes(), "application/pdf"))]
            ).status_code
            == 200
        )
        assert client.post("/api/correction/start").status_code == 200
        state = wait(client)
        assert len(state["results"]) == 1
        assert state["results"][0]["variant"] == 42
        # Sujet vierge : n° étudiant illisible -> malus de 1 appliqué à la note.
        assert state["results"][0]["note"] == -1
        assert state["results"][0]["malus"] == 1
        response = client.post("/api/pages/0/student", json={"student_id": "p1234567"})
        assert response.json()["student_id"] == "p1234567"
        assert session.notes == {"p1234567": -1.0}  # malus de 1 (n° étudiant illisible)
        assert client.get("/api/pages/0/image").content.startswith(b"\x89PNG")
        assert session.page_image(0, raw=True).startswith(b"\x89PNG")
        before = session.results()
        archive = client.get("/api/state/save")
        assert archive.status_code == 200
        assert client.post("/api/copies/remove", json={"indices": [0]}).json()["results"] == []
        assert client.post("/api/state/load", files={"file": ("correction.zip", archive.content)}).status_code == 200
        after = wait(client)["results"]
        for key in ("variant", "student_id", "note", "status"):
            assert after[0][key] == before[0][key]


def test_saisie_manuelle_de_la_variante(project_path, tmp_path):
    """Code-barres illisible : la variante saisie relit les cases et recalcule la note (fenêtre GTK agrandie)."""
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    session = Session(work_dir=str(tmp_path))
    session.load_project(project_path)
    session.add_copy("sujet.pdf", pdf.read_bytes())
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        assert client.post("/api/correction/start").status_code == 200
        wait(client)
        page = session.pages[0].page
        expected = client.get("/api/pages/0").json()
        page.variant_id, page.marks, page.value = None, [], None  # simule un code-barres illisible
        assert client.get("/api/pages/0").json()["status"] == "Code-barres non trouvé"
        assert client.post("/api/pages/0/variant", json={"variant_id": "abc"}).status_code == 400
        assert client.post("/api/pages/0/variant", json={"variant_id": "999"}).status_code == 400
        info = client.post("/api/pages/0/variant", json={"variant_id": "42"}).json()
        for key in ("variant", "note", "total", "status"):
            assert info[key] == expected[key]
        n_marks = len(page.marks)
        client.post("/api/pages/0/variant", json={"variant_id": "42"})
        assert len(page.marks) == n_marks  # une seconde saisie ne double pas les cases


def test_correction_cli_et_reprise(project_path, tmp_path, capsys):
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    saved = tmp_path / "correction.json"
    output = tmp_path / "notes.csv"
    args = ["correct", "-p", project_path, "-c", str(pdf), "-o", str(output)]
    assert cli.main(args + ["--save", str(saved), "--render", str(tmp_path)]) == 0
    assert saved.exists()
    assert list(tmp_path.glob("sujet_v42_*.png"))
    with output.open() as stream:
        assert next(csv.reader(stream)) == ["eid", "note", "total"]
    initial = output.read_bytes()
    assert cli.main(args + ["--load", str(saved)]) == 0
    assert "état restauré" in capsys.readouterr().out
    assert output.read_bytes() == initial


def test_malus_manuel_met_a_jour_les_notes_et_resiste_a_la_recorrection(project_path, tmp_path):
    """Un malus saisi à la main est pris en compte dans les notes et n'est pas écrasé."""
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    (tmp_path / "session4").mkdir()
    session = Session(work_dir=str(tmp_path / "session4"))
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        client.post("/api/project/open", files={"file": ("projet.json", Path(project_path).read_bytes())})
        client.post("/api/copies", files=[("files", ("sujet.pdf", pdf.read_bytes(), "application/pdf"))])
        client.post("/api/correction/start")
        wait(client)
        client.post("/api/pages/0/student", json={"student_id": "p1234567"})
        assert session.notes == {"p1234567": -1.0}
        # Changer le malus doit mettre à jour les notes exportées.
        client.post("/api/pages/0/malus", json={"malus": 0})
        assert session.notes == {"p1234567": 0.0}
        client.post("/api/pages/0/malus", json={"malus": 3})
        assert session.notes == {"p1234567": -3.0}
        # Forcer la variante relance la correction sans écraser le malus manuel.
        response = client.post("/api/pages/0/variant", json={"variant_id": "42"})
        assert response.json()["malus"] == 3
