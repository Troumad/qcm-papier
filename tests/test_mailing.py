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


def test_send_all_compte_non_configure():
    with pytest.raises(mailing.MailingError, match="non configuré"):
        mailing.send_all([mailing.Recipient(email="a@x.fr")], "S", "B")


def test_send_all_aucun_destinataire():
    with pytest.raises(mailing.MailingError, match="Aucun destinataire"):
        mailing.send_all([], "S", "B")
