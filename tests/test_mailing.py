"""Envoi des copies corrigées par mail : groupement et construction des messages."""

import pytest

from qcm_papier import mailing  # noqa: E402


class FakePage:
    """Page corrigée minimale pour le groupement par email."""

    def __init__(self, email="", name="", firstname="", student_id="", ok=True):
        self.student_email = email
        self.student_name = name
        self.student_firstname = firstname
        self.student_id = student_id
        self.matrix_inv = object() if ok else None
        self.variant_id = 1234 if ok else None
        self.marks = []
        self.value = 0.0
        self.total = 0.0
        self.malus = 0.0


def test_group_by_email():
    pages = [
        ("a.pdf", FakePage(email="jean@x.fr", name="DUPONT", firstname="Jean", student_id="p1")),
        ("b.pdf", FakePage(email="jean@x.fr", name="DUPONT", firstname="Jean", student_id="p1")),
        ("c.pdf", FakePage(email="marie@x.fr", name="MARTIN", firstname="Marie", student_id="p2")),
        ("d.pdf", FakePage(email="", student_id="p3")),
        ("e.pdf", FakePage(email="abs@x.fr", ok=False)),
    ]
    recipients = mailing.group_by_email(pages)
    assert len(recipients) == 2
    by_mail = {r.email: r for r in recipients}
    assert len(by_mail["jean@x.fr"].pages) == 2
    assert by_mail["jean@x.fr"].display == "DUPONT Jean"
    assert len(by_mail["marie@x.fr"].pages) == 1
    # Sans email ou sans correction : exclu.


def test_group_by_email_sans_adresse():
    assert mailing.group_by_email([("a.pdf", FakePage())]) == []


def test_build_message_une_piece_jointe(monkeypatch):
    page = FakePage(email="jean@x.fr", name="DUPONT", firstname="Jean")
    png = b"\x89PNG fake data"
    monkeypatch.setattr(mailing, "page_png_bytes", lambda p: png)
    recipient = mailing.Recipient(email="jean@x.fr", name="DUPONT Jean", pages=[page])
    msg = mailing.build_message(recipient, "Sujet", "Corps", "prof@univ.fr")
    assert msg["To"] == "DUPONT Jean <jean@x.fr>"
    assert msg["From"] == "prof@univ.fr"
    assert msg["Subject"] == "Sujet"
    attachments = [p for p in msg.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "image/png"
    assert attachments[0].get_filename() == "copie.png"
    assert attachments[0].get_payload(decode=True) == png


def test_build_message_plusieurs_pages(monkeypatch):
    pages = [
        FakePage(email="jean@x.fr", student_id="p1"),
        FakePage(email="jean@x.fr", student_id="p1"),
    ]
    monkeypatch.setattr(mailing, "page_png_bytes", lambda p: b"img")
    recipient = mailing.Recipient(email="jean@x.fr", name="DUPONT Jean", pages=pages)
    msg = mailing.build_message(recipient, "Sujet", "Corps", "prof@univ.fr", "Prof")
    assert msg["From"] == "Prof <prof@univ.fr>"
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 2
    names = [a.get_filename() for a in attachments]
    assert names[0].startswith("copie_p1_")
    assert names[1].startswith("copie_p1_")


def test_send_all_compte_non_configure(monkeypatch, tmp_path):
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    with pytest.raises(mailing.MailingError, match="non configuré"):
        mailing.send_all([mailing.Recipient(email="a@x.fr")], "S", "B", password="x")


def test_send_all_aucun_destinataire():
    with pytest.raises(mailing.MailingError, match="Aucun destinataire"):
        mailing.send_all([], "S", "B")


def test_question_breakdown():
    from qcm_papier.model import Choice, Exercise, Project, Question

    q1 = Question(name="Q1", gain=2.0, choices=[Choice(correct=True, index=0), Choice(penalty=True, index=1)])
    q2 = Question(name="Q2", gain=3.0, manual=True)
    ex = Exercise(name="Exercice 1", questions=[q1, q2])
    project = Project(structure=[ex])
    project.settings.evaluation_full = "DS de test"

    # Q1 : case correcte cochée ; Q2 : réponse libre notée 1,5.
    marks = [
        {"e": 0, "q": 0, "c": 0, "r": 2.0, "checked": True},
        {"e": 0, "q": 1, "r": None, "c": None, "value": 1.5},
    ]

    page = FakePage(email="jean@x.fr", name="DUPONT", firstname="Jean", student_id="p1")
    page.marks = marks
    text = mailing.question_breakdown(project, page)
    assert "Exercice 1 : 3.5/5" in text
    assert "- Q1 : 2/2" in text
    assert "- Q2 : 1.5/3" in text


def test_build_message_avec_ds_et_decompte(monkeypatch):
    from qcm_papier.model import Choice, Exercise, Project, Question

    q1 = Question(
        name="Q1",
        gain=2.0,
        choices=[Choice(correct=True, neutral=False, penalty=False, index=0), Choice(index=1)],
    )
    project = Project(structure=[Exercise(name="Exo", questions=[q1])])
    project.settings.evaluation_full = "DS de mathématiques"

    page = FakePage(email="jean@x.fr", name="DUPONT", firstname="Jean", student_id="p1")
    page.marks = [{"e": 0, "q": 0, "c": 0, "r": 2.0, "checked": True}]

    monkeypatch.setattr(mailing, "page_png_bytes", lambda p: b"img")
    recipient = mailing.Recipient(email="jean@x.fr", name="DUPONT Jean", pages=[page])
    msg = mailing.build_message(
        recipient,
        "Sujet",
        "Corps",
        "prof@univ.fr",
        project=project,
        ds_name="DS de mathématiques",
        include_breakdown=True,
    )
    content = msg.get_body(preferencelist=("plain",)).get_content()
    assert "DS : DS de mathématiques" in content
    assert "Décompte des points par question" in content
    assert "- Q1 : 2/2" in content


def test_note_line_avec_malus_et_sur_20():
    page = FakePage(email="jean@x.fr")
    page.value = 12.0
    page.total = 24.0
    page.malus = 1.0
    line = mailing.note_line(page)
    assert "note brute : 12/24" in line
    assert "malus : 1" in line
    assert "note finale : 11/24" in line
    assert "ramenée sur 20 : 9.17/20" in line

    page.malus = 0.0
    line = mailing.note_line(page)
    assert "note brute : 12/24" in line
    assert "note finale" not in line
    assert "ramenée sur 20 : 10.00/20" in line


def test_note_line_total_deja_20():
    page = FakePage(email="jean@x.fr")
    page.value = 12.0
    page.total = 20.0
    page.malus = 0.0
    line = mailing.note_line(page)
    assert line == "note brute : 12/20"
    assert "ramenée" not in line


def test_project_mailed_persiste():
    from qcm_papier.model import Project

    p = Project()
    p.mailed.add("jean@x.fr")
    d = p.to_dict()
    assert d["mailed"] == ["jean@x.fr"]
    p2 = Project.from_dict(d)
    assert p2.mailed == {"jean@x.fr"}
