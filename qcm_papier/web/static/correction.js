"use strict";
// Onglet Correction : copies, correction par lot, résultats, Scodoc,
// sauvegarde/reprise et visionneuse avec alignement manuel.

(() => {
  const { $, api, guard, toast, download, el, onTab } = window.QCM;

  let state = { copies: [], results: [], job: {}, clair: 140, notes: 0 };
  let current = -1; // page affichée
  let sort = { key: null, dir: 1 };
  let pollTimer = null;

  // -------------------------------------------------------------------------
  // Chargement et affichage
  // -------------------------------------------------------------------------
  async function refresh(data) {
    state = data || (await api("GET", "/api/correction"));
    renderCopies();
    renderResults();
    renderStatus();
    if (document.activeElement !== $("#clair")) $("#clair").value = state.clair;
    if (state.job.running) schedulePoll();
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => guard(async () => {
      const wasRunning = state.job.running;
      await refresh();
      if (wasRunning && !state.job.running) {
        if (state.job.error) toast(state.job.error, true);
        if (state.results.length) showPage(Math.max(0, Math.min(current, state.results.length - 1)));
      }
    }), 500);
  }

  function renderStatus() {
    const { job } = state;
    const status = $("#marking-status");
    status.classList.toggle("error", Boolean(job.error));
    if (job.running) status.textContent = `${job.message || "En cours…"} (${job.done}/${job.total})`;
    else if (job.error) status.textContent = `Erreur : ${job.error}`;
    else status.textContent = job.message || `${state.copies.length} copie(s) chargée(s).`;
  }

  function renderCopies() {
    const list = $("#copies");
    list.replaceChildren(...state.copies.map((copy, i) => {
      const rest = Math.max(0, copy.n_pages - copy.n_ok - copy.n_err);
      const total = copy.n_ok + copy.n_err + rest;
      const part = (n, cls) => el("span", { class: cls, style: `width:${total ? (100 * n) / total : 0}%` }, n ? String(n) : "");
      return el("li", {},
        el("input", {
          type: "checkbox", checked: copy.checked, "aria-label": `Corriger ${copy.name}`,
          onchange: (ev) => guard(async () => refresh(await api("PATCH", `/api/copies/${i}`, { checked: ev.target.checked }))),
        }),
        el("span", { class: "name" }, copy.name),
        el("span", { class: "bar", title: `${copy.n_ok} lue(s), ${copy.n_err} en erreur` },
          part(copy.n_ok, "ok"), part(copy.n_err, "err"), part(total ? rest : 0, "rest")));
    }));
  }

  function sortedResults() {
    const rows = state.results.slice();
    if (!sort.key) return rows;
    return rows.sort((a, b) => {
      const va = sort.key === "note" ? (a.note ?? -Infinity) : String(a[sort.key] ?? "");
      const vb = sort.key === "note" ? (b.note ?? -Infinity) : String(b[sort.key] ?? "");
      return (va > vb ? 1 : va < vb ? -1 : 0) * sort.dir;
    });
  }

  function pageLabel(r) {
    return r.failed && r.note === null ? `${r.file} ⚠ ${r.status}` : `${r.file} v${r.variant} ${r.student_id || ""}`;
  }

  function renderResults() {
    const body = $("#results tbody");
    body.replaceChildren(...sortedResults().map((r) => {
      const row = el("tr", { onclick: () => showPage(r.index), ondblclick: () => openViewer(r.index) },
        el("td", {}, r.file),
        el("td", {}, r.variant ?? ""),
        el("td", {}, r.student),
        el("td", {}, r.note === null ? "" : r.note.toFixed(2)),
        el("td", { class: r.failed ? "failed" : "" }, r.status));
      row.classList.toggle("selected", r.index === current);
      return row;
    }));
    document.querySelectorAll("#results th").forEach((th) => {
      th.classList.toggle("asc", sort.key === th.dataset.sort && sort.dir === 1);
      th.classList.toggle("desc", sort.key === th.dataset.sort && sort.dir === -1);
    });
    const select = $("#page-select");
    select.replaceChildren(...state.results.map((r) => el("option", { value: r.index, selected: r.index === current }, pageLabel(r))));
    if (!state.results.length) {
      current = -1;
      $("#page-preview").hidden = true;
    }
  }

  function imageUrl(index, raw = false) {
    return `/api/pages/${index}/image?raw=${raw}&t=${Date.now()}`;
  }

  function showPage(index) {
    if (index < 0 || index >= state.results.length) return;
    current = index;
    $("#page-select").value = String(index);
    const img = $("#page-preview");
    img.src = imageUrl(index);
    img.hidden = false;
    document.querySelectorAll("#results tbody tr").forEach((tr, i) => {
      tr.classList.toggle("selected", sortedResults()[i].index === index);
    });
  }

  document.querySelectorAll("#results th").forEach((th) => th.addEventListener("click", () => {
    sort = { key: th.dataset.sort, dir: sort.key === th.dataset.sort ? -sort.dir : 1 };
    renderResults();
  }));
  $("#page-select").addEventListener("change", (ev) => showPage(Number(ev.target.value)));
  $("#btn-prev").addEventListener("click", () => showPage(Math.max(0, current - 1)));
  $("#btn-next").addEventListener("click", () => showPage(Math.min(state.results.length - 1, current + 1)));
  $("#btn-enlarge").addEventListener("click", () => current >= 0 && openViewer(current));

  // -------------------------------------------------------------------------
  // Copies, correction, sauvegarde
  // -------------------------------------------------------------------------
  function uploadFiles(input, url, field, after) {
    input.addEventListener("change", () => guard(async () => {
      if (!input.files.length) return;
      const body = new FormData();
      for (const file of input.files) body.append(field, file);
      input.value = "";
      const data = await api("POST", url, body);
      await after(data);
    }));
  }

  $("#btn-add-copies").addEventListener("click", () => $("#input-copies").click());
  uploadFiles($("#input-copies"), "/api/copies", "files", refresh);
  $("#btn-run").addEventListener("click", () => guard(async () => refresh(await api("POST", "/api/correction/start"))));
  $("#clair").addEventListener("change", (ev) => guard(async () => refresh(await api("PUT", "/api/correction/clair", { clair: Number(ev.target.value) }))));
  $("#btn-save-state").addEventListener("click", () => guard(async () => {
    await download("/api/state/save", "correction.zip");
    toast("État de correction sauvegardé.");
  }));
  $("#btn-load-state").addEventListener("click", () => $("#input-state").click());
  uploadFiles($("#input-state"), "/api/state/load", "file", refresh);

  // -------------------------------------------------------------------------
  // Boîtes de dialogue
  // -------------------------------------------------------------------------
  document.querySelectorAll("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

  function loadScodocImages(dialog) {
    dialog.querySelectorAll("img.scodoc").forEach((img) => {
      if (img.src) return;
      img.onerror = () => img.replaceWith(el("p", { class: "muted" },
        `(Capture d'écran ${img.dataset.src} absente — voir qcm_papier/data/scodoc/ pour l'ajouter.)`));
      img.src = `/api/scodoc/images/${img.dataset.src}`;
    });
  }

  $("#btn-students").addEventListener("click", () => {
    loadScodocImages($("#dlg-students"));
    $("#students-status").textContent = "";
    $("#dlg-students").showModal();
  });
  uploadFiles($("#input-students"), "/api/scodoc/students", "file", async (data) => {
    const status = $("#students-status");
    status.className = "status ok";
    status.textContent = data.message;
    await refresh(data);
    if (current >= 0) showPage(current);
  });

  $("#btn-export").addEventListener("click", () => {
    if (!state.notes) {
      toast("Aucune note à exporter : corrigez d'abord.", true);
      return;
    }
    loadScodocImages($("#dlg-export"));
    $("#export-status").textContent = "";
    $("#dlg-export").showModal();
  });
  $("#btn-do-export").addEventListener("click", () => guard(async () => {
    const status = $("#export-status");
    const file = $("#input-export").files[0];
    if (!file) {
      status.className = "status error";
      status.textContent = "Choisissez d'abord le fichier tableur.";
      return;
    }
    const body = new FormData();
    body.append("file", file);
    body.append("min0", $("#export-min0").checked ? "true" : "false");
    const response = await fetch("/api/scodoc/export", { method: "POST", body });
    if (!response.ok) throw new Error((await response.json()).detail);
    const link = el("a", { href: URL.createObjectURL(await response.blob()), download: "notes_scodoc.xlsx" });
    link.click();
    status.className = "status ok";
    status.textContent = `${response.headers.get("X-Notes-Count")} note(s) exportée(s) → notes_scodoc.xlsx`;
  }));

  $("#btn-remove").addEventListener("click", () => {
    if (!state.copies.length) {
      toast("Aucune copie à supprimer.", true);
      return;
    }
    $("#remove-list").replaceChildren(...state.copies.map((copy, i) => el("li", {},
      el("label", { class: "check" }, el("input", { type: "checkbox", value: i }), copy.name))));
    $("#dlg-remove").showModal();
  });
  $("#btn-do-remove").addEventListener("click", () => guard(async () => {
    const indices = [...$("#remove-list").querySelectorAll("input:checked")].map((c) => Number(c.value));
    $("#dlg-remove").close();
    await refresh(await api("POST", "/api/copies/remove", { indices }));
    if (state.results.length) showPage(0);
  }));

  // -------------------------------------------------------------------------
  // Visionneuse : zoom, n° étudiant, alignement manuel
  // -------------------------------------------------------------------------
  const viewer = { index: -1, zoom: 1, aligning: false, points: [] };
  const vImg = $("#viewer-img");
  const canvas = $("#viewer-canvas");

  function setZoom(value) {
    viewer.zoom = Math.max(0.25, Math.min(4, Math.round(value * 4) / 4));
    $("#zoom").value = viewer.zoom;
    $("#zoom-label").textContent = `${Math.round(viewer.zoom * 100)} %`;
    layoutStage();
  }

  function layoutStage() {
    if (!vImg.naturalWidth) return;
    const w = vImg.naturalWidth * viewer.zoom;
    const h = vImg.naturalHeight * viewer.zoom;
    vImg.style.width = `${w}px`;
    vImg.style.height = `${h}px`;
    canvas.width = w;
    canvas.height = h;
    drawPoints();
  }

  function drawPoints() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!viewer.aligning) return;
    ctx.font = "14px system-ui, sans-serif";
    viewer.points.forEach(([x, y], i) => {
      const px = x * viewer.zoom;
      const py = y * viewer.zoom;
      ctx.fillStyle = "rgba(255,0,0,0.8)";
      ctx.beginPath();
      ctx.arc(px, py, 10, 0, 2 * Math.PI);
      ctx.fill();
      ctx.strokeStyle = "red";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px - 14, py); ctx.lineTo(px + 14, py);
      ctx.moveTo(px, py - 14); ctx.lineTo(px, py + 14);
      ctx.stroke();
      ctx.fillText(`${i + 1} (${Math.round(x)},${Math.round(y)})`, px + 14, py - 10);
    });
  }

  function alignLabel(text = "", cls = "status") {
    const label = $("#v-align-label");
    label.className = cls;
    const rest = 5 - viewer.points.length;
    if (text) label.textContent = text;
    else if (!viewer.aligning) label.textContent = "";
    else label.textContent = rest > 1 ? `Cliquer les ${rest} repères restants (à gauche de haut en bas, puis à droite de bas en haut).` : "Cliquer le dernier repère.";
  }

  async function loadViewer(index) {
    viewer.index = index;
    viewer.aligning = false;
    viewer.points = [];
    $("#v-align").setAttribute("aria-pressed", "false");
    $("#viewer-stage").classList.remove("aligning");
    alignLabel();
    const info = await api("GET", `/api/pages/${index}`);
    $("#v-index").textContent = `Copie ${index + 1} / ${state.results.length}`;
    $("#v-variant").textContent = `Variante : ${info.variant ?? "—"}`;
    $("#v-student").textContent = info.failed && info.note === null ? `⚠ ${info.status}` : `Étudiant : ${info.student_id || "—"} ${info.student !== info.student_id ? info.student : ""}`;
    $("#v-note").textContent = info.note === null ? "Note : —" : `Note : ${info.note.toFixed(2)} / ${Math.round(info.total ?? 20)}`;
    $("#v-status").textContent = `Statut : ${info.status}`;
    $("#v-status").className = info.failed || !info.complete ? "status error" : "status ok";
    $("#v-student-id").value = info.student_id || "";
    $("#v-prev").disabled = index <= 0;
    $("#v-next").disabled = index >= state.results.length - 1;
    vImg.onload = layoutStage;
    vImg.src = imageUrl(index);
  }

  async function afterPageChange(index) {
    await refresh();
    showPage(index);
    await loadViewer(index);
  }

  function openViewer(index) {
    $("#dlg-viewer").showModal();
    guard(() => loadViewer(index));
  }

  $("#zoom").addEventListener("input", (ev) => setZoom(Number(ev.target.value)));
  $("#zoom-in").addEventListener("click", () => setZoom(viewer.zoom + 0.25));
  $("#zoom-out").addEventListener("click", () => setZoom(viewer.zoom - 0.25));
  $("#viewer-scroll").addEventListener("wheel", (ev) => {
    if (!ev.ctrlKey) return;
    ev.preventDefault();
    setZoom(viewer.zoom - Math.sign(ev.deltaY) * 0.25);
  }, { passive: false });
  $("#v-prev").addEventListener("click", () => guard(async () => { await loadViewer(viewer.index - 1); showPage(viewer.index); }));
  $("#v-next").addEventListener("click", () => guard(async () => { await loadViewer(viewer.index + 1); showPage(viewer.index); }));
  $("#v-apply-student").addEventListener("click", () => guard(async () => {
    await api("POST", `/api/pages/${viewer.index}/student`, { student_id: $("#v-student-id").value });
    await afterPageChange(viewer.index);
  }));

  $("#v-align").addEventListener("click", () => {
    viewer.aligning = !viewer.aligning;
    viewer.points = [];
    $("#v-align").setAttribute("aria-pressed", String(viewer.aligning));
    $("#viewer-stage").classList.toggle("aligning", viewer.aligning);
    vImg.onload = layoutStage;
    vImg.src = imageUrl(viewer.index, viewer.aligning);
    alignLabel();
  });
  $("#v-align-reset").addEventListener("click", () => {
    if (!viewer.aligning) return;
    viewer.points = [];
    drawPoints();
    alignLabel();
  });
  canvas.addEventListener("click", (ev) => guard(async () => {
    if (!viewer.aligning || viewer.points.length >= 5) return;
    const x = Math.max(0, Math.min(vImg.naturalWidth, ev.offsetX / viewer.zoom));
    const y = Math.max(0, Math.min(vImg.naturalHeight, ev.offsetY / viewer.zoom));
    viewer.points.push([x, y]);
    drawPoints();
    alignLabel();
    if (viewer.points.length < 5) return;
    alignLabel("Alignement terminé ✓ — correction en cours…", "status ok");
    const result = await api("POST", `/api/pages/${viewer.index}/align`, { points: viewer.points });
    if (!result.ok) {
      alignLabel("Alignement impossible (repères mal placés ? Reprendre les 5 repères).", "status error");
      return;
    }
    await afterPageChange(viewer.index);
    const note = result.note === null ? "—" : result.note.toFixed(2);
    toast(`Alignement manuel réussi ✓ — variante ${result.variant ?? "—"}, note ${note} (${result.status})`);
  }));

  // -------------------------------------------------------------------------
  // Démarrage
  // -------------------------------------------------------------------------
  onTab("correct", () => guard(() => refresh()));
  document.addEventListener("project-reset", () => guard(() => refresh()));
})();
