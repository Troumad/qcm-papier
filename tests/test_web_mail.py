"""Interface web : compte mail et envoi des copies corrigées."""

import smtplib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qcm_papier import cli, mailing
from qcm_papier.web.server import create_app
from qcm_papier.web.session import Session

EMAIL = "jean.dupont@etu.x.fr"


def wait_mail(client):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = client.get("/api/mail").json()
        if not state["running"]:
            return state
        time.sleep(0.02)
    raise AssertionError("Envoi trop long")


@pytest.fixture
def smtp(monkeypatch, tmp_path):
    """Compte configuré, serveur SMTP simulé, sans attentes réelles."""
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(mailing, "RETRY_DELAY", 0)
    monkeypatch.setattr(mailing, "RECONNECT_DELAY", 0)
    monkeypatch.setattr(mailing, "PACING_DELAY", 0)
    state = {"sent": [], "script": [], "passwords": []}

    class Server:
        def send_message(self, msg):
            if state["script"]:
                raise state["script"].pop(0) if len(state["script"]) > 1 else state["script"][0]
            state["sent"].append(msg)

        def quit(self):
            pass

    def connection(password=None):
        state["passwords"].append(password)
        return Server()

    monkeypatch.setattr(mailing, "smtp_connection", connection)
    return state


@pytest.fixture
def client(project_path, tmp_path, smtp):
    pdf = tmp_path / "sujet.pdf"
    cli.main(["generate", "-p", project_path, "-o", str(pdf), "--save-project", project_path])
    (tmp_path / "work").mkdir()
    session = Session(work_dir=str(tmp_path / "work"))
    with TestClient(create_app(session), base_url="http://127.0.0.1:8060") as c:
        c.post("/api/project/open", files={"file": ("projet.json", Path(project_path).read_bytes())})
        c.post("/api/copies", files=[("files", ("sujet.pdf", pdf.read_bytes(), "application/pdf"))])
        c.post("/api/correction/start")
        deadline = time.monotonic() + 30
        while c.get("/api/correction").json()["job"]["running"]:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        page = session.pages[0].page
        page.student_id, page.student_eid = "p1234567", "42"
        page.student_name, page.student_firstname, page.student_email = "DUPONT", "Jean", EMAIL
        c.put("/api/settings/mail", json={"host": "smtp.x.fr", "port": 587, "username": "prof", "sender": "prof@x.fr"})
        yield c, session


def test_compte_mail_sans_mot_de_passe(client):
    c, _ = client
    account = c.get("/api/settings/mail").json()
    assert account == {
        "host": "smtp.x.fr",
        "port": 587,
        "username": "prof",
        "sender": "prof@x.fr",
        "starttls": True,
        "complete": True,
    }
    response = c.put("/api/settings/mail", json={"host": "", "port": 587, "username": "u", "sender": "s"})
    assert response.status_code == 400
    assert c.delete("/api/settings/mail").json()["complete"] is False


def test_resume_avant_envoi(client):
    c, _ = client
    state = c.get("/api/mail").json()
    assert (state["recipients"], state["pages"], state["already"]) == (1, 1, 0)
    assert state["subject"].startswith("Votre copie corrigée")
    assert state["account"]["complete"] is True
    assert c.get("/api/correction").json()["results"][0]["email"] == EMAIL


def test_mot_de_passe_obligatoire(client, smtp):
    c, _ = client
    response = c.post("/api/mail/send", json={"password": ""})
    assert response.status_code == 400
    assert "mot de passe" in response.json()["detail"].lower()
    assert smtp["passwords"] == []


def test_envoi_memorise_et_jamais_garde_le_mot_de_passe(client, smtp):
    c, session = client
    assert c.post("/api/mail/send", json={"password": "secret", "include_breakdown": True}).status_code == 200
    state = wait_mail(c)
    assert [r["sent"] for r in state["reports"]] == [True]
    assert smtp["passwords"] == ["secret"]
    assert smtp["sent"][0]["To"] == f"DUPONT Jean <{EMAIL}>"
    assert "Décompte des points" in smtp["sent"][0].get_body().get_content()
    assert session.project.mailed == {EMAIL}
    assert c.get("/api/correction").json()["results"][0]["mailed"] is True
    assert c.get("/api/mail").json()["already"] == 1
    assert "secret" not in str(vars(session)) and "secret" not in str(state)


def test_mode_test_envoie_a_l_expediteur(client, smtp):
    c, session = client
    c.post("/api/mail/send", json={"password": "secret", "selftest": True})
    wait_mail(c)
    assert smtp["sent"][0]["To"] == '"[Test → DUPONT Jean]" <prof@x.fr>'
    assert session.project.mailed == set()


def test_envoi_individuel_a_une_autre_adresse(client, smtp):
    c, session = client
    c.post("/api/mail/send", json={"password": "secret", "index": 0, "address": "autre@x.fr"})
    wait_mail(c)
    assert smtp["sent"][0]["To"] == "DUPONT Jean <autre@x.fr>"
    assert session.project.mailed == {"autre@x.fr"}


def test_annulation_pendant_les_essais(client, smtp):
    c, _ = client
    smtp["script"] = [smtplib.SMTPDataError(421, b"Rate limit exceeded")]  # refus temporaire permanent
    c.post("/api/mail/send", json={"password": "secret"})
    time.sleep(0.05)
    # Pendant l'envoi : les modifications sont refusées, l'annulation non.
    assert c.post("/api/pages/0/malus", json={"malus": 2}).status_code == 409
    assert c.post("/api/mail/skip").status_code == 200
    state = wait_mail(c)
    assert [r["sent"] for r in state["reports"]] == [False]
    assert state["reports"][0]["kind"].startswith("Limite de taux")


def test_annuler_l_envoi(client, smtp):
    c, session = client
    smtp["script"] = [smtplib.SMTPDataError(421, b"Rate limit exceeded")]
    c.post("/api/mail/send", json={"password": "secret"})
    time.sleep(0.05)
    assert c.post("/api/mail/cancel").status_code == 200
    state = wait_mail(c)
    assert [r["kind"] for r in state["reports"]] == ["Envoi annulé"]
    assert session.project.mailed == set()
    assert state["job"]["message"] == "0 mail(s) envoyé(s), 1 échec(s) — envoi annulé."


def test_envoi_ne_salit_pas_la_correction(client):
    c, _ = client
    before = c.get("/api/work").json()["correction_token"]
    c.post("/api/mail/send", json={"password": "secret"})
    wait_mail(c)
    work = c.get("/api/work").json()
    assert work["correction_token"] == before
    assert work["project_dirty"] is True  # les envoyés sont mémorisés dans le projet
