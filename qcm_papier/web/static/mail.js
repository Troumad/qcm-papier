"use strict";
// Envoi des copies corrigées par mail : toutes les copies ou celle d'une page.
// Le mot de passe SMTP part vers le serveur local pour cet envoi seulement ;
// il n'est jamais mémorisé et le champ est vidé après chaque envoi.

(() => {
  const { $, api, guard, el, showTab } = window.QCM;
  const dialog = $("#dlg-mail");
  let target = null; // index de page pour un envoi individuel, sinon null
  let pollTimer = null;
  let running = false;

  function status(text, cls = "status") {
    const node = $("#mail-status");
    node.className = cls;
    node.textContent = text;
  }

  function setRunning(value) {
    running = value;
    $("#mail-send").disabled = value;
    $("#mail-close").textContent = value ? "Annuler l'envoi" : "Fermer";
    $("#mail-close").disabled = false;
    if (!value) $("#mail-skip").hidden = true;
  }

  function showReports(state) {
    const failed = state.reports.filter((r) => !r.sent);
    const groups = new Map();
    for (const r of failed) groups.set(r.kind, [...(groups.get(r.kind) || []), r.name]);
    $("#mail-failures").replaceChildren(...[...groups].map(([kind, names]) => el("li", {},
      `${kind} (${names.length}) : ${names.slice(0, 5).join(", ")}${names.length > 5 ? ` … et ${names.length - 5} autre(s)` : ""}`)));
    const job = state.job || {};
    if (job.error) status(`Erreur : ${job.error}`, "status error");
    else status(job.message || "", failed.length ? "status error" : "status ok");
    // Tout est parti : Envoyer reste désactivé pour éviter un double envoi.
    $("#mail-send").disabled = !job.error && !failed.length && state.reports.length > 0;
  }

  function poll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => guard(async () => {
      const state = await api("GET", "/api/mail");
      if (state.running) {
        status(`${state.job.message || "Connexion au serveur SMTP…"}`);
        $("#mail-skip").hidden = !state.retrying;
        poll();
        return;
      }
      setRunning(false);
      showReports(state);
      document.dispatchEvent(new CustomEvent("qcm:mail-done"));
    }), 400);
  }

  async function open(index = null) {
    target = index;
    const [state, results] = await Promise.all([api("GET", "/api/mail"), api("GET", "/api/correction")]);
    const page = index === null ? null : results.results.find((r) => r.index === index);
    if (index === null && !state.total) {
      throw new Error("Aucune adresse : chargez la table étudiants (levée d'anonymat) puis corrigez.");
    }
    $("#mail-title").textContent = page ? `Envoyer la copie de ${page.student || page.email}` : "Envoyer les copies par mail";
    $("#mail-summary").textContent = page
      ? `Copie : ${page.file}${page.note === null ? "" : ` — note ${page.note}/${page.total}`}`
      : `${state.recipients} destinataire(s), ${state.pages} copie(s) corrigée(s). `
        + (state.already ? `${state.already} étudiant(s) ont déjà reçu leur copie (mémorisés dans le projet). ` : "")
        + "Chaque étudiant reçoit un mail individuel avec ses copies (PNG) en pièces jointes.";
    const account = state.account;
    const accountLine = $("#mail-account");
    accountLine.replaceChildren();
    if (account.complete) {
      accountLine.className = "status muted";
      accountLine.textContent = `Expéditeur : ${account.sender} — serveur ${account.host}:${account.port}`;
    } else {
      accountLine.className = "status error";
      accountLine.append(account.error ? `Compte mail illisible : ${account.error} ` : "Compte mail non configuré. ",
        el("button", { type: "button", onclick: () => { dialog.close(); showTab("settings"); } }, "Configurer le compte mail…"));
    }
    $("#mail-address-label").hidden = !page;
    $("#mail-address").value = page ? page.email : "";
    $("#mail-subject").value = state.subject;
    if (!$("#mail-body").value) $("#mail-body").value = state.body;
    $("#mail-resend-label").hidden = Boolean(page) || !state.already;
    $("#mail-resend").checked = false;
    $("#mail-selftest").checked = false;
    $("#mail-password").value = "";
    $("#mail-failures").replaceChildren();
    status("");
    setRunning(state.running);
    $("#mail-send").disabled = state.running || !account.complete;
    dialog.showModal();
    if (state.running) poll();
  }

  $("#mail-send").addEventListener("click", () => guard(async () => {
    const password = $("#mail-password").value;
    if (!password) {
      status("⚠ Mot de passe manquant : saisissez le mot de passe SMTP (jamais mémorisé, demandé à chaque envoi).", "status error");
      $("#mail-password").focus();
      return;
    }
    const body = {
      password,
      subject: $("#mail-subject").value,
      body: $("#mail-body").value,
      include_breakdown: $("#mail-breakdown").checked,
      selftest: $("#mail-selftest").checked,
      resend: $("#mail-resend").checked,
    };
    if (target !== null) Object.assign(body, { index: target, address: $("#mail-address").value });
    $("#mail-failures").replaceChildren();
    status("Connexion au serveur SMTP…");
    setRunning(true);
    try {
      await api("POST", "/api/mail/send", body);
    } catch (error) {
      setRunning(false);
      status(error.message, "status error");
      return;
    } finally {
      $("#mail-password").value = "";
    }
    poll();
  }));

  // Pendant l'envoi, le bouton annule (après le mail en cours) au lieu de fermer.
  $("#mail-close").addEventListener("click", () => guard(async () => {
    if (!running) { dialog.close(); return; }
    $("#mail-close").textContent = "Annulation…";
    $("#mail-close").disabled = true;
    await api("POST", "/api/mail/cancel");
  }));
  $("#mail-skip").addEventListener("click", () => guard(() => api("POST", "/api/mail/skip")));
  // Échap ne ferme pas la fenêtre pendant un envoi : le compte-rendu arrive à la fin.
  dialog.addEventListener("cancel", (event) => { if (running) event.preventDefault(); });

  $("#btn-mail").addEventListener("click", () => guard(() => open(null)));
  window.QCMMail = { open: (index) => guard(() => open(index)) };
})();
