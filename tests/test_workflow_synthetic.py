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
        assert state["results"][0]["note"] == 0
        response = client.post("/api/pages/0/student", json={"student_id": "p1234567"})
        assert response.json()["student_id"] == "p1234567"
        assert session.notes == {"p1234567": 0.0}
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
