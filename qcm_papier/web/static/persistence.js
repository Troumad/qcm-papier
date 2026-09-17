"use strict";
// Le serveur distingue le projet de la correction ; seul un export réussi valide son instantané.
(() => {
  const { $, api, toast } = window.QCM;
  const native = window.__TAURI__?.core;
  let work = { project_dirty: false, correction_dirty: false, running: false };
  let pending = 0;
  let draft = false;
  let draftVersion = 0;
  let saving = false;
  let confirming = false;
  let path = null;
  let refreshVersion = 0;

  function render() {
    const parts = [];
    if (pending) parts.push("Modification en cours…");
    if (work.project_dirty || draft) parts.push("Projet non enregistré");
    if (work.correction_dirty) parts.push("Correction non sauvegardée");
    if (work.running) parts.push("Correction en cours");
    if (work.variants_stale) parts.push("Sujet modifié : régénérez les variantes avant le PDF");
    $("#save-status").textContent = parts.join(" · ") || "Aucune modification en attente";
    $("#btn-save-as").hidden = !native;
    $("#btn-download").hidden = Boolean(native);
  }
  async function refresh() {
    const version = ++refreshVersion;
    const next = await api("GET", "/api/work");
    if (version === refreshVersion) { work = next; render(); }
    return next;
  }
  async function settle() {
    document.activeElement?.blur();
    while (pending) await new Promise((resolve) => setTimeout(resolve, 30));
    await refresh();
  }
  async function deliver(response, fallbackName, options = {}) {
    if (saving) throw new Error("Un enregistrement est déjà en cours.");
    saving = true;
    try {
      const disposition = response.headers.get("Content-Disposition") || "";
      const name = disposition.match(/filename="([^"]+)"/)?.[1] || fallbackName;
      const blob = await response.blob();
      if (native) {
        const target = await native.invoke("save_document", {
          data: Array.from(new Uint8Array(await blob.arrayBuffer())), name,
          project: Boolean(options.project), saveAs: Boolean(options.saveAs),
        });
        if (!target) return false;
        if (options.project) path = target;
        toast(`Enregistré : ${target}`);
      } else {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 10000);
        toast("Téléchargement lancé : vérifiez le fichier dans vos téléchargements.");
      }
      const projectToken = response.headers.get("X-Project-Token");
      const correctionToken = response.headers.get("X-Correction-Token");
      if (projectToken || correctionToken !== null) {
        await api("POST", "/api/work/saved", {
          project_token: projectToken,
          correction_token: correctionToken === null ? null : Number(correctionToken),
        });
        await refresh();
      }
      return true;
    } finally { saving = false; }
  }
  async function remindProjectSave() {
    const shouldSave = await new Promise((resolve) => {
      const dialog = $("#dlg-pdf-json");
      const finish = (value) => { dialog.close(); resolve(value); };
      $("#pdf-json-save").onclick = () => finish(true);
      $("#pdf-json-later").onclick = () => finish(false);
      dialog.oncancel = (event) => { event.preventDefault(); finish(false); };
      dialog.showModal();
      $("#pdf-json-save").focus();
    });
    $("#generate-status").textContent = "PDF exporté. Conservez le JSON correspondant : il est indispensable pour corriger les copies.";
    if (shouldSave && await saveProject()) {
      $("#generate-status").textContent = "PDF et projet JSON exportés. Conservez-les ensemble pour la correction.";
    }
  }
  async function saveProject(saveAs = false) {
    await settle();
    if (work.running) throw new Error("Attendez la fin de la correction pour enregistrer.");
    const response = await api("GET", "/api/project/download", undefined, { raw: true });
    const saved = await deliver(response, "projet.json", { project: true, saveAs });
    if (saved) $("#file-status").textContent = path || "Téléchargement du projet lancé.";
    return saved;
  }
  async function openProject() {
    if (!native) { $("#input-project").click(); return; }
    if (!(await beforeReplace())) return;
    const chosen = await native.invoke("open_document");
    if (!chosen) return;
    const [name, content] = chosen;
    const body = new FormData();
    body.append("file", new Blob([content], { type: "application/json" }), name);
    const data = await api("POST", "/api/project/open", body);
    path = await native.invoke("accept_document");
    draft = false;
    window.QCM.applyProject(data);
    $("#file-status").textContent = `Projet chargé : ${path || name}`;
    document.dispatchEvent(new CustomEvent("project-reset"));
    await refresh();
  }
  async function resetPath() {
    if (native) await native.invoke("reset_document");
    path = null;
    draft = false;
    await refresh();
  }
  function choice() {
    return new Promise((resolve) => {
      const dialog = $("#dlg-unsaved");
      $("#unsaved-message").textContent = work.correction_dirty
        ? "Le projet, les copies et les résultats seront conservés dans une archive ZIP. Continuer sans enregistrer abandonne le travail non sauvegardé."
        : "Enregistrez le projet avant de le remplacer ou de fermer l'application.";
      const finish = (value) => { dialog.close(); resolve(value); };
      $("#unsaved-save").onclick = () => finish("save");
      $("#unsaved-discard").onclick = () => finish("discard");
      $("#unsaved-cancel").onclick = () => finish("cancel");
      dialog.oncancel = (event) => { event.preventDefault(); finish("cancel"); };
      dialog.showModal();
      $("#unsaved-cancel").focus();
    });
  }
  async function beforeReplace() {
    if (confirming || saving) return false;
    confirming = true;
    try {
      await settle();
      if (work.running) { toast("Attendez la fin de la correction.", true); return false; }
      if (!work.project_dirty && !work.correction_dirty && !draft) return true;
      const answer = await choice();
      if (answer === "discard") return true;
      if (answer !== "save") return false;
      const saved = work.correction_dirty
        ? await deliver(await api("GET", "/api/state/save"), "correction.zip")
        : await saveProject();
      return Boolean(saved) && !work.project_dirty && !work.correction_dirty && !draft;
    } finally { confirming = false; }
  }
  window.QCMSave = {
    refresh, settle, deliver, saveProject, beforeReplace, resetPath, openProject, remindProjectSave,
    beginMutation() { pending += 1; render(); return draftVersion; },
    async endMutation(ok, version) {
      try { await refresh(); if (ok && version === draftVersion) draft = false; }
      finally { pending -= 1; render(); }
    },
  };
  for (const selector of ["#info-form", "#gen-form", "#props"]) {
    $(selector).addEventListener("input", () => { draft = true; draftVersion += 1; render(); });
  }
  window.addEventListener("beforeunload", (event) => {
    if (pending || saving || draft || work.project_dirty || work.correction_dirty || work.running) {
      event.preventDefault(); event.returnValue = "";
    }
  });
  window.addEventListener("qcm-close-requested", () => window.QCM.guard(async () => {
    if (await beforeReplace()) await native.invoke("close_document");
  }));
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault(); window.QCM.guard(() => saveProject(event.shiftKey));
    }
  });
  window.QCM.guard(async () => {
    await refresh();
    if (native) await native.invoke("desktop_ready");
  });
})();
