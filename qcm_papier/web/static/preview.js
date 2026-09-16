"use strict";
// Aperçu du sujet : lecteur PDF intégré à l'interface.
//
// Le serveur rend chaque page en PNG avec PyMuPDF (`/api/generate/preview`),
// comme il le fait déjà pour les copies corrigées. L'aperçu fonctionne donc
// dans toutes les fenêtres, y compris celle de l'application Tauri sous Linux,
// où un PDF placé dans un cadre reste blanc.

(() => {
  const { $, api, guard, download } = window.QCM;

  const DPI_BASE = 110;                                   // 100 % à l'écran
  const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3];
  const dialog = $("#dlg-pdf");
  const image = $("#pdf-image");
  const select = $("#pdf-page-select");

  let pages = 0;
  let current = 0;
  let zoom = ZOOMS.indexOf(1);
  let objectUrl = null;
  let token = 0;  // Un rendu lent ne doit pas écraser une page demandée depuis.

  function updateControls() {
    $("#pdf-prev").disabled = current === 0;
    $("#pdf-next").disabled = current >= pages - 1;
    $("#pdf-zoom-out").disabled = zoom === 0;
    $("#pdf-zoom-in").disabled = zoom === ZOOMS.length - 1;
    $("#pdf-zoom-label").textContent = `${Math.round(ZOOMS[zoom] * 100)} %`;
    $("#pdf-count").textContent = pages ? `sur ${pages}` : "";
  }

  async function show(index) {
    if (!pages) return;
    current = Math.min(Math.max(index, 0), pages - 1);
    select.value = String(current);
    updateControls();
    const mine = ++token;
    image.classList.add("loading");
    const dpi = Math.round(DPI_BASE * ZOOMS[zoom]);
    const response = await api("GET", `/api/generate/preview/${current}?dpi=${dpi}`);
    const blob = await response.blob();
    if (mine !== token) return;  // Une autre page a été demandée entre-temps.
    releaseImage();
    objectUrl = URL.createObjectURL(blob);
    image.src = objectUrl;
    image.classList.remove("loading");
    $("#pdf-status").textContent = "";
  }

  function releaseImage() {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  async function open() {
    $("#pdf-status").textContent = "Création du sujet…";
    image.removeAttribute("src");
    pages = 0;
    updateControls();
    if (!dialog.open) dialog.showModal();
    try {
      const data = await api("GET", "/api/generate/preview");
      pages = data.pages;
      select.replaceChildren(...Array.from({ length: pages }, (_, i) => {
        const option = document.createElement("option");
        option.value = String(i);
        option.textContent = String(i + 1);
        return option;
      }));
      await show(0);
    } catch (error) {
      dialog.close();  // Sujet impossible à produire : pas de fenêtre vide.
      throw error;
    }
  }

  function setZoom(delta) {
    const next = Math.min(Math.max(zoom + delta, 0), ZOOMS.length - 1);
    if (next === zoom) return;
    zoom = next;
    return show(current);
  }

  $("#btn-gen-preview").addEventListener("click", () => guard(open));
  $("#pdf-prev").addEventListener("click", () => guard(() => show(current - 1)));
  $("#pdf-next").addEventListener("click", () => guard(() => show(current + 1)));
  select.addEventListener("change", () => guard(() => show(Number(select.value))));
  $("#pdf-zoom-out").addEventListener("click", () => guard(() => setZoom(-1)));
  $("#pdf-zoom-in").addEventListener("click", () => guard(() => setZoom(+1)));
  $("#pdf-download").addEventListener("click", () => guard(() => download("/api/generate/pdf", "sujet.pdf")));
  dialog.addEventListener("close", releaseImage);

  // Flèches et touches page pour feuilleter, sans gêner la liste déroulante.
  dialog.addEventListener("keydown", (event) => {
    if (event.target === select) return;
    const step = { ArrowLeft: -1, PageUp: -1, ArrowRight: +1, PageDown: +1 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    guard(() => show(current + step));
  });
})();
