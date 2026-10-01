"""Correction des questions à réponse libre : saisie des points et aide à la correction."""

import time

import pytest
from fastapi.testclient import TestClient

from qcm_papier import cli, editing, model, project
from qcm_papier.web.server import create_app
from qcm_papier.web.session import Session


@pytest.fixture
def open_project_path(tmp_path):
    """Sujet synthétique : une question à cocher et une question ouverte notée sur 2."""
    value = model.Project()
    value.settings.generate_variants = "42"
    value.settings.generate_count = 1
    value.structure = [
        model.Exercise(
            name="Exercice",
            index=0,
            questions=[
                model.Question(
                    name="QCM",
                    index=0,
                    choices=[
                        model.Choice(name="Oui", index=0, correct=True, neutral=False),
                        model.Choice(name="Non", index=1, penalty=True, neutral=False),
                    ],
                ),
                model.Question(
                    name="Justifier",
                    index=1,
                    gain=2.0,
                    manual=True,
                    width=60.0,
                    height=25.0,
                    expected="La dérivée est nulle.",
                    grading_notes="1 pt pour le calcul, 1 pt pour la conclusion.",
                ),
            ],
        )
    ]
    path = tmp_path / "projet.json"
    project.save_project(value, str(path))
    return str(path)


def wait(client):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = client.get("/api/correction").json()
        if not state["job"]["running"]:
            assert state["job"]["error"] == ""
            return state
        time.sleep(0.05)
    raise AssertionError("Correction trop longue")


@pytest.fixture
def corrected(open_project_path, tmp_path):
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", open_project_path, "-o", str(pdf), "--save-project", open_project_path])
    session = Session(work_dir=str(tmp_path / "session"))
    session.load_project(open_project_path)
    session.add_copy("sujet.pdf", pdf.read_bytes())
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as client:
        assert client.post("/api/correction/start").status_code == 200
        wait(client)
        client.post("/api/pages/0/student", json={"student_id": "p1234567"})
        yield client, session


# -- Modèle et édition ----------------------------------------------------------


def test_aide_a_la_correction_conservee_dans_le_projet():
    question = model.Question(manual=True, expected="Réponse", grading_notes="Barème")
    loaded = model.Question.from_dict(question.to_dict())
    assert (loaded.expected, loaded.grading_notes) == ("Réponse", "Barème")


def test_aide_absente_ne_change_pas_le_format_du_projet():
    data = model.Question().to_dict()
    assert "expected" not in data
    assert "grading_notes" not in data


def test_edition_du_cadre_et_de_l_aide():
    question = model.Question()
    editing.update_question(question, {"type": "manual"})
    assert question.width > 0 and question.height > 0  # cadre par défaut, sinon rien à scanner
    editing.update_question(
        question, {"width": 80, "height": 30, "expected": "x = 2", "grading_notes": "Méthode : 1 pt"}
    )
    assert (question.width, question.height) == (80.0, 30.0)
    assert (question.expected, question.grading_notes) == ("x = 2", "Méthode : 1 pt")
    with pytest.raises(ValueError):
        editing.update_question(question, {"width": 0})


def test_vue_de_la_structure_expose_le_cadre_et_l_aide():
    value = model.Project()
    value.structure = [model.Exercise(questions=[model.Question(manual=True, width=50, height=20, expected="E")])]
    question = editing.structure_view(value)["exercises"][0]["questions"][0]
    assert (question["width"], question["height"], question["expected"], question["grading_notes"]) == (
        50,
        20,
        "E",
        "",
    )


# -- Saisie des points ------------------------------------------------------------


def test_question_ouverte_a_noter_rend_la_copie_incomplete(corrected):
    client, _ = corrected
    page = client.get("/api/pages/0").json()
    assert page["complete"] is False
    data = client.get("/api/manual").json()
    assert [q["name"] for q in data["questions"]] == ["Justifier"]
    question = data["questions"][0]
    assert (question["e"], question["q"], question["gain"]) == (0, 1, 2.0)
    assert question["expected"] == "La dérivée est nulle."
    assert question["grading_notes"].startswith("1 pt")
    assert question["remaining"] == 1
    assert question["rows"] == [{"index": 0, "student": "p1234567", "file": "sujet.pdf", "value": None}]


def test_image_de_la_zone_de_reponse(corrected):
    client, session = corrected
    response = client.get("/api/pages/0/manual/0/1/image")
    assert response.headers["content-type"] == "image/png"
    from io import BytesIO

    from PIL import Image

    crop = Image.open(BytesIO(response.content))
    full = session.pages[0].page.img.img
    assert 0 < crop.width < full.width and 0 < crop.height < full.height
    assert crop.width > crop.height  # cadre de 60 × 25 mm
    assert client.get("/api/pages/0/manual/0/0/image").status_code == 400  # question à cocher


def test_saisie_des_points_complete_la_copie(corrected):
    client, session = corrected
    page = client.put("/api/pages/0/manual/0/1", json={"value": 1.5}).json()
    assert page["complete"] is True
    assert page["note"] == 1.5
    assert session.notes == {"p1234567": 1.5}
    question = client.get("/api/manual").json()["questions"][0]
    assert question["rows"][0]["value"] == 1.5
    assert question["remaining"] == 0
    assert client.get("/api/work").json()["correction_dirty"] is True


def test_points_hors_bareme_refuses(corrected):
    client, _ = corrected
    assert client.put("/api/pages/0/manual/0/1", json={"value": 2.5}).status_code == 400
    assert client.put("/api/pages/0/manual/0/1", json={"value": -1}).status_code == 400
    assert client.put("/api/pages/0/manual/0/1", json={"value": "abc"}).status_code == 400
    assert client.put("/api/pages/0/manual/0/0", json={"value": 1}).status_code == 400


def test_effacer_les_points(corrected):
    client, _ = corrected
    client.put("/api/pages/0/manual/0/1", json={"value": 2})
    page = client.put("/api/pages/0/manual/0/1", json={"value": None}).json()
    assert page["complete"] is False
    assert client.get("/api/manual").json()["questions"][0]["remaining"] == 1


def test_points_conserves_par_la_sauvegarde(corrected):
    client, _ = corrected
    client.put("/api/pages/0/manual/0/1", json={"value": 2})
    archive = client.get("/api/state/save").content
    client.post("/api/copies/remove", json={"indices": [0]})
    client.post("/api/state/load", files={"file": ("correction.zip", archive)})
    wait(client)
    assert client.get("/api/manual").json()["questions"][0]["rows"][0]["value"] == 2
    assert client.get("/api/pages/0").json()["complete"] is True


def test_intervalle_de_notes_d_une_question_ouverte():
    """Une réponse libre vaut de 0 à son gain, comme dans le calcul de la note (marking)."""
    question = model.Question(manual=True, gain=2.0, penalty=1.0)
    assert question.get_mark_range() == (0.0, 2.0)
    qcm = model.Question(gain=1.0, choices=[model.Choice(correct=True, neutral=False)])
    exercise = model.Exercise(questions=[qcm, question])
    assert exercise.get_mark_range() == (0.0, 3.0)


def test_lecture_des_points_tapes_au_clavier():
    from qcm_papier.manual_grading import parse_points

    assert parse_points("1,5") == 1.5
    assert parse_points(" 2 ") == 2.0
    assert parse_points("") is None
    with pytest.raises(ValueError):
        parse_points("abc")
