"""Envoi des copies corrigées par mail (PNG en pièce jointe).

Les pages corrigées sont rendues en PNG (overlay vert/rouge, comme dans
l'interface) et envoyées en pièces jointes, une adresse par étudiant.
Le compte SMTP vient de ``mail_config`` (mot de passe dans le trousseau).
"""

from __future__ import annotations

import io
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr

from . import mail_config, marking


class MailingError(Exception):
    """Erreur d'envoi (compte non configuré, refus du serveur…)."""


@dataclass
class Recipient:
    """Un étudiant destinataire avec ses pages corrigées."""

    email: str
    name: str = ""
    pages: list = field(default_factory=list)

    @property
    def display(self) -> str:
        return self.name or self.email


@dataclass
class SendReport:
    """Résultat d'envoi pour un destinataire."""

    recipient: Recipient
    sent: bool
    error: str = ""


def group_by_email(marked_pages: list) -> list[Recipient]:
    """Regroupe les pages corrigées par adresse email d'étudiant.

    ``marked_pages`` : liste de ``(label, page)`` comme dans l'interface.
    Seules les pages avec un email connu sont retenues ; les pages
    correspondant au même étudiant (même email) sont regroupées.
    """
    groups: dict[str, Recipient] = {}
    for _label, page in marked_pages:
        email = (getattr(page, "student_email", None) or "").strip()
        if not email:
            continue
        if page.matrix_inv is None or page.variant_id is None:
            continue
        recipient = groups.get(email)
        if recipient is None:
            name = f"{page.student_name or ''} {page.student_firstname or ''}".strip()
            recipient = Recipient(email=email, name=name)
            groups[email] = recipient
        recipient.pages.append(page)
    return list(groups.values())


def page_png_bytes(page) -> bytes | None:
    """Rend une page corrigée en PNG (overlay vert/rouge), ou None."""
    from . import scanner

    img = scanner.render_marked_page(page)
    if img is None:
        return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def question_breakdown(project, page) -> str:
    """Décompte des points par exercice et par question d'une copie.

    Reprend le calcul de ``marking.score_page`` question par question
    (``_question_score``) pour afficher la ligne de chaque question :
    nom, points obtenus / points possibles.
    """
    lines: list[str] = []
    for i, exercise in enumerate(project.structure):
        ex_value = 0.0
        ex_total = 0.0
        q_lines: list[str] = []
        for q, question in enumerate(exercise.questions):
            value, total, ok = marking._question_score(question, page.marks, i, q)
            if not question.check and not question.manual:
                continue
            ex_value += value
            ex_total += total
            label = question.name or f"Question {q + 1}"
            flag = "" if ok else " (incomplète)"
            if question.manual:
                q_lines.append(f"  - {label} : {value:g}/{total:g}{flag}")
            else:
                q_lines.append(f"  - {label} : {value:g}/{total:g}{flag}")
        if q_lines:
            lines.append(f"{exercise.name or f'Exercice {i + 1}'} : {ex_value:g}/{ex_total:g}")
            lines.extend(q_lines)
    return "\n".join(lines)


def note_line(page) -> str:
    """Ligne de résumé de la note d'une page : « note : X/T (Y/20) ».

    La note ramenée sur 20 n'est ajoutée que si le total du QCM n'est
    pas déjà 20. ``with_malus`` ajoute le détail du malus quand il est
    non nul.
    """
    from . import marking, scanner

    note = scanner.final_value(page)
    brute = float(page.value) if page.value is not None else 0.0
    total = float(page.total) if page.total is not None else 0.0
    malus = float(getattr(page, "malus", 0.0) or 0.0)
    txt = f"note brute : {brute:g}/{total:g}"
    if malus:
        txt += f" — malus : {malus:g} — note finale : {note:g}/{total:g}"
    if total and abs(total - 20.0) > 1e-9:
        sur20 = marking.scale_note(note or 0.0, total, note_max=20.0, notemax=total)
        txt += f" — ramenée sur 20 : {sur20:.2f}/20"
    return txt


def malus_line(page) -> str:
    """Ligne de résumé du malus et de la note d'une page (vide si pas de malus)."""
    malus = float(getattr(page, "malus", 0.0) or 0.0)
    if not malus:
        return ""
    return note_line(page)


def build_message(
    recipient: Recipient,
    subject: str,
    body: str,
    sender_email: str,
    sender_name: str = "",
    project=None,
    ds_name: str = "",
    include_breakdown: bool = False,
) -> EmailMessage:
    """Construit le mail d'un destinataire avec ses copies en pièces jointes."""
    msg = EmailMessage()
    if sender_name:
        msg["From"] = formataddr((sender_name, sender_email))
    else:
        msg["From"] = sender_email
    msg["To"] = formataddr((recipient.display, recipient.email)) if recipient.name else recipient.email
    msg["Subject"] = subject
    text = body
    if ds_name:
        text = f"DS : {ds_name}\n\n{text}"
    if include_breakdown and project is not None:
        parts = []
        for page in recipient.pages:
            chunk = question_breakdown(project, page)
            line = note_line(page)
            if line:
                chunk = f"{chunk}\n{line}" if chunk else line
            if chunk:
                parts.append(chunk)
        breakdown = "\n\n".join(parts)
        if breakdown:
            text += "\n\nDécompte des points par question :\n\n" + breakdown
    msg.set_content(text)
    multiple = len(recipient.pages) > 1
    for i, page in enumerate(recipient.pages, 1):
        data = page_png_bytes(page)
        if data is None:
            continue
        if not multiple:
            filename = "copie.png"
        else:
            student_id = getattr(page, "student_id", None) or i
            filename = f"copie_{student_id}_{i}.png"
        msg.add_attachment(
            data,
            maintype="image",
            subtype="png",
            filename=filename,
        )
    return msg


def smtp_connection(password: str | None = None):
    """Connexion SMTP authentifiée à partir du compte enregistré.

    ``password`` : mot de passe saisi par l'utilisateur à l'envoi, jamais
    stocké. Vide : certains serveurs acceptent une session sans
    authentification (relais interne).
    """
    account = mail_config.load_account()
    if not account.complete:
        raise MailingError("Compte mail non configuré : bouton « Compte mail… ».")
    password = password or ""
    try:
        server = smtplib.SMTP(account.host, account.port, timeout=30)
        if account.starttls:
            server.starttls(context=ssl.create_default_context())
    except (OSError, smtplib.SMTPException) as exc:
        raise MailingError(f"Connexion à {account.host}:{account.port} impossible : {exc}") from exc
    if password:
        try:
            server.login(account.username, password)
        except smtplib.SMTPException as exc:
            raise MailingError(f"Authentification refusée : {exc}") from exc
    return server


def send_all(
    recipients: list[Recipient],
    subject: str,
    body: str,
    sender_email: str = "",
    sender_name: str = "",
    progress=None,
    project=None,
    password: str | None = None,
    ds_name: str = "",
    include_breakdown: bool = False,
) -> list[SendReport]:
    """Envoie les copies à chaque destinataire, un mail par étudiant.

    Renvoie un rapport par destinataire (envoyé ou erreur). ``progress``
    (facultatif) est appelé avec ``(index, total, recipient)`` avant chaque
    envoi pour rafraîchir l'interface.
    """
    if not recipients:
        raise MailingError("Aucun destinataire : chargez la table étudiants et corrigez d'abord.")
    account = mail_config.load_account()
    if not sender_email:
        sender_email = account.sender or account.username
    reports: list[SendReport] = []
    total = len(recipients)
    server = smtp_connection(password)
    try:
        for i, recipient in enumerate(recipients, 1):
            if progress is not None:
                progress(i, total, recipient)
            msg = build_message(
                recipient,
                subject,
                body,
                sender_email,
                sender_name,
                project=project,
                ds_name=ds_name,
                include_breakdown=include_breakdown,
            )
            try:
                server.send_message(msg)
                reports.append(SendReport(recipient, sent=True))
            except smtplib.SMTPException as exc:
                reports.append(SendReport(recipient, sent=False, error=str(exc)))
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass
    return reports
