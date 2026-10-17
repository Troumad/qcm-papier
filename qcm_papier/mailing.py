"""Envoi des copies corrigées par mail (PNG en pièce jointe).

Les pages corrigées sont rendues en PNG (overlay vert/rouge, comme dans
l'interface) et envoyées en pièces jointes, une adresse par étudiant.
Le compte SMTP vient de ``mail_config`` (mot de passe dans le trousseau).
"""

from __future__ import annotations

import io
import smtplib
import ssl
import time
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

    @property
    def mail_key(self) -> str:
        return self.recipient.email

    @property
    def error_kind(self) -> str:
        """Type d'erreur en clair (analyse du code/message SMTP)."""
        if self.sent or not self.error:
            return ""
        e = self.error.lower()
        if any(k in e for k in ("blacklist", "blocklist", "spamhaus", "barracuda", "dnsbl", "rbl")):
            return "Blacklist : adresse IP ou domaine sur liste de blocage, contacter l'administrateur"
        if "blocked" in e or "client host rejected" in e:
            return "Client bloqué par le serveur : politique anti-spam ou blacklist"
        if "421" in e and "rate" in e:
            return "Limite de taux du serveur (421) : envois trop rapides, ralentir ou attendre"
        if "421" in e:
            return "Connexion fermée par le serveur (421)"
        if "451" in e:
            return "Erreur temporaire du serveur (451) : réessayer plus tard"
        if "550" in e or "551" in e or "553" in e:
            return "Adresse refusée (550) : destinataire ou expéditeur invalide"
        if "552" in e:
            return "Boîte du destinataire pleine ou message trop volumineux (552)"
        if "554" in e:
            return "Message refusé (554) : contenu jugé indésirable ou bloqué"
        if "535" in e or "authenti" in e:
            return "Authentification refusée : vérifiez le login et le mot de passe"
        if "connect() first" in e:
            return "Connexion perdue avec le serveur"
        if "timed out" in e or "timeout" in e:
            return "Délai dépassé : le serveur n'a pas répondu"
        if "connection" in e or "network" in e or "refus" in e:
            return "Problème de connexion réseau au serveur"
        return "Erreur inconnue du serveur"


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
    mailed: set[str] | None = None,
    cancelled: list | None = None,
    skip: list | None = None,
) -> list[SendReport]:
    """Envoie les copies à chaque destinataire, un mail par étudiant.

    Renvoie un rapport par destinataire (envoyé ou erreur). ``progress``
    (facultatif) est appelé avec ``(index, total, ok, échecs)`` avant chaque
    envoi pour rafraîchir l'interface.

    ``mailed`` : ensemble complété avec l'email de chaque destinataire
    ayant reçu son mail avec succès (mémorisation pour la reprise).
    ``cancelled`` : si cette liste devient truthy, l'envoi s'arrête
    proprement après le mail en cours.
    """
    if not recipients:
        raise MailingError("Aucun destinataire : chargez la table étudiants et corrigez d'abord.")
    account = mail_config.load_account()
    if not sender_email:
        sender_email = account.sender or account.username
    reports: list[SendReport] = []
    total = len(recipients)

    ok_count = 0
    fail_count = 0

    def _send_one(server, recipient):
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
        server.send_message(msg)
        return msg

    # skip[0] : passer au destinataire suivant sans retenter le mail en
    # cours (bouton « Passer au suivant » du dialogue).
    skip_one: list = []
    if skip is not None:
        skip_one = skip

    def _try_send(recipient):
        """Un essai d'envoi avec reconnexions ; boucle tant que le serveur
        limite le taux, avec compteur, sauf « Passer au suivant »."""
        nonlocal server
        rate_retries = 0
        while True:
            try:
                _send_one(server, recipient)
                reports.append(SendReport(recipient, sent=True))
                return True
            except smtplib.SMTPServerDisconnected:
                server = smtp_connection(password)
            except smtplib.SMTPException as exc:
                rate_retries += 1
                # Pas de plafond d'essais : si le serveur limite le taux, il
                # bloquera pareillement le destinataire suivant. Seul le
                # bouton « Passer au suivant » (ou l'annulation) fait passer.
                if skip_one and skip_one[0]:
                    reports.append(SendReport(recipient, sent=False, error=str(exc)))
                    skip_one.clear()
                    return False
                # Décompte des secondes d'attente, avec le numéro d'essai.
                for sec in range(10, 0, -1):
                    if skip_one and skip_one[0]:
                        break
                    if progress is not None:
                        progress(
                            i_holder[0],
                            total,
                            ok_count,
                            fail_count,
                            rate_retries,
                            seconds=sec,
                        )
                    time.sleep(1)
                server = smtp_connection(password)

    i_holder = [0]
    server = smtp_connection(password)
    try:
        for i, recipient in enumerate(recipients, 1):
            if cancelled is not None and cancelled:
                break
            i_holder[0] = i
            if progress is not None:
                progress(i, total, ok_count, fail_count)
            if _try_send(recipient):
                ok_count += 1
                if mailed is not None:
                    mailed.add(recipient.email)
            else:
                fail_count += 1
            time.sleep(1)  # pace les envois pour respecter la limite du serveur
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass
    return reports
