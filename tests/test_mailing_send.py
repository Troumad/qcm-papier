"""Boucle d'envoi des mails : erreurs temporaires/définitives, annulation, reconnexions."""

import smtplib

import pytest

from qcm_papier import mail_config, mailing


class FakeServer:
    """Serveur SMTP simulé : ``script`` donne, par adresse, la suite des réponses."""

    def __init__(self, script, log, on_send=None):
        self.script = script
        self.log = log
        self.on_send = on_send

    def send_message(self, msg):
        email = msg["To"]
        self.log.append(email)
        if self.on_send is not None:
            self.on_send(email)
        outcomes = self.script.get(email, [])
        outcome = outcomes.pop(0) if outcomes else None
        if outcome is not None:
            raise outcome

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch, tmp_path):
    """Remplace la connexion SMTP et supprime les attentes réelles."""
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    mail_config.save_account("smtp.x.fr", 587, "prof", "prof@x.fr")
    monkeypatch.setattr(mailing, "RETRY_DELAY", 0)
    monkeypatch.setattr(mailing, "RECONNECT_DELAY", 0)
    monkeypatch.setattr(mailing, "PACING_DELAY", 0)
    monkeypatch.setattr(mailing, "page_png_bytes", lambda page: None)
    state = {"script": {}, "log": [], "connections": 0, "on_send": None, "fail_connect_after": None}

    def connection(password=None):
        state["connections"] += 1
        limit = state["fail_connect_after"]
        if limit is not None and state["connections"] > limit:
            raise mailing.MailingError("Connexion à smtp.x.fr:587 impossible : refusée")
        return FakeServer(state["script"], state["log"], state["on_send"])

    monkeypatch.setattr(mailing, "smtp_connection", connection)
    return state


def _recipients(*emails):
    return [mailing.Recipient(email=e) for e in emails]


def test_adresse_refusee_definitivement_n_est_pas_reessayee(smtp):
    smtp["script"]["bad@x.fr"] = [smtplib.SMTPRecipientsRefused({"bad@x.fr": (550, b"User unknown")})]
    mailed: set[str] = set()
    reports = mailing.send_all(_recipients("bad@x.fr", "ok@x.fr"), "S", "B", mailed=mailed)
    assert smtp["log"] == ["bad@x.fr", "ok@x.fr"]
    assert [r.sent for r in reports] == [False, True]
    assert reports[0].error_kind.startswith("Adresse refusée")
    assert mailed == {"ok@x.fr"}


def test_erreur_temporaire_reessayee_jusqu_au_succes(smtp):
    rate = smtplib.SMTPDataError(421, b"Rate limit exceeded")
    smtp["script"]["a@x.fr"] = [rate, rate]
    progress = []
    reports = mailing.send_all(_recipients("a@x.fr"), "S", "B", progress=lambda *a, **k: progress.append((a, k)))
    assert smtp["log"] == ["a@x.fr"] * 3
    assert reports[0].sent
    assert any(a[4] == 2 for a, _k in progress if len(a) > 4)  # 2e essai refusé signalé


def test_annulation_pendant_les_essais(smtp):
    control = mailing.SendControl()
    rate = smtplib.SMTPDataError(421, b"Rate limit exceeded")
    smtp["script"]["a@x.fr"] = [rate] * 1000

    def on_send(email):
        if len(smtp["log"]) == 3:
            control.cancel()

    smtp["on_send"] = on_send
    reports = mailing.send_all(_recipients("a@x.fr", "b@x.fr"), "S", "B", control=control)
    assert smtp["log"] == ["a@x.fr"] * 3
    assert [r.sent for r in reports] == [False]
    assert reports[0].error_kind == "Envoi annulé"


def test_passer_au_suivant_pendant_les_essais(smtp):
    control = mailing.SendControl()
    rate = smtplib.SMTPDataError(421, b"Rate limit exceeded")
    smtp["script"]["a@x.fr"] = [rate] * 1000

    def on_send(email):
        if email == "a@x.fr" and len(smtp["log"]) == 2:
            control.skip()

    smtp["on_send"] = on_send
    reports = mailing.send_all(_recipients("a@x.fr", "b@x.fr"), "S", "B", control=control)
    assert [r.sent for r in reports] == [False, True]
    assert smtp["log"].count("a@x.fr") == 2


def test_deconnexions_repetees_limitees(smtp):
    drop = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    smtp["script"]["a@x.fr"] = [drop] * 1000
    reports = mailing.send_all(_recipients("a@x.fr", "b@x.fr"), "S", "B")
    assert smtp["log"].count("a@x.fr") == mailing.MAX_RECONNECTS + 1
    assert [r.sent for r in reports] == [False, True]
    assert reports[0].error_kind == "Connexion perdue avec le serveur"


def test_reconnexion_impossible_garde_les_rapports(smtp):
    smtp["fail_connect_after"] = 1
    smtp["script"]["b@x.fr"] = [smtplib.SMTPServerDisconnected("closed")]
    mailed: set[str] = set()
    with pytest.raises(mailing.MailingError) as err:
        mailing.send_all(_recipients("a@x.fr", "b@x.fr", "c@x.fr"), "S", "B", mailed=mailed)
    assert [r.sent for r in err.value.reports] == [True, False]
    assert mailed == {"a@x.fr"}


@pytest.mark.parametrize(
    ("code", "transient"),
    [(421, True), (450, True), (451, True), (452, True), (550, False), (552, False), (554, False)],
)
def test_classement_des_erreurs(code, transient):
    assert mailing.is_transient(smtplib.SMTPDataError(code, b"x")) is transient


def test_attente_interrompue_par_annulation():
    import time

    control = mailing.SendControl()
    control.cancel()
    start = time.monotonic()
    control.wait(5)
    assert time.monotonic() - start < 0.5


def test_passer_en_attente_ne_vise_pas_le_destinataire_suivant(smtp):
    control = mailing.SendControl()
    control.skip()  # clic tardif, avant le début de l'envoi
    rate = smtplib.SMTPDataError(421, b"Rate limit exceeded")
    smtp["script"]["a@x.fr"] = [rate]
    reports = mailing.send_all(_recipients("a@x.fr"), "S", "B", control=control)
    assert reports[0].sent


class _Recorder:
    def __init__(self, kind, calls):
        self.kind = kind
        self.calls = calls

    def __call__(self, host, port, **kwargs):
        self.calls.append((self.kind, host, port))
        return self

    def starttls(self, **kwargs):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user))


def _connect(monkeypatch, tmp_path, port, starttls):
    monkeypatch.setenv("QCM_PAPIER_CONFIG_DIR", str(tmp_path))
    mail_config.save_account("smtp.x.fr", port, "prof", "prof@x.fr", starttls=starttls)
    calls: list = []
    monkeypatch.setattr(mailing.smtplib, "SMTP", _Recorder("smtp", calls))
    monkeypatch.setattr(mailing.smtplib, "SMTP_SSL", _Recorder("ssl", calls))
    return calls


def test_port_465_ssl_direct(monkeypatch, tmp_path):
    calls = _connect(monkeypatch, tmp_path, 465, starttls=False)
    mailing.smtp_connection("secret")
    assert calls == [("ssl", "smtp.x.fr", 465), ("login", "prof")]


def test_port_587_starttls(monkeypatch, tmp_path):
    calls = _connect(monkeypatch, tmp_path, 587, starttls=True)
    mailing.smtp_connection("secret")
    assert calls == [("smtp", "smtp.x.fr", 587), ("starttls",), ("login", "prof")]


def test_mot_de_passe_jamais_en_clair(monkeypatch, tmp_path):
    calls = _connect(monkeypatch, tmp_path, 25, starttls=False)
    with pytest.raises(mailing.MailingError, match="non chiffrée"):
        mailing.smtp_connection("secret")
    assert calls == []
    mailing.smtp_connection(None)  # relais interne sans authentification : accepté
    assert calls == [("smtp", "smtp.x.fr", 25)]
