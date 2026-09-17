"use strict";
// Interface web QCM-Papier : outils communs, onglets Fichier, Informations,
// Structure, Génération et Aide. L'onglet Correction est dans correction.js.

const $ = (selector, root = document) => root.querySelector(selector);

async function api(method, url, body, { raw = false } = {}) {
  const options = { method };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const tracking = method !== "GET" && !url.startsWith("/api/work");
  const draftVersion = tracking ? window.QCMSave?.beginMutation() : null;
  let succeeded = false;
  try {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `Erreur ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* réponse non JSON */ }
    throw new Error(detail);
  }
  succeeded = true;
  const type = response.headers.get("Content-Type") || "";
  if (!raw && type.includes("application/json")) return response.json();
  return response;
  } finally {
    if (tracking) await window.QCMSave?.endMutation(succeeded, draftVersion);
  }
}

let toastTimer;
function toast(message, isError = false) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, isError ? 6000 : 3000);
}

// Exécute une action et affiche l'erreur éventuelle.
async function guard(action) {
  try { return await action(); } catch (error) { toast(error.message, true); return undefined; }
}

async function download(url, fallbackName) {
  await window.QCMSave.settle();
  const response = await api("GET", url, undefined, { raw: true });
  if (!(await window.QCMSave.deliver(response, fallbackName))) return null;
  if (url === "/api/generate/pdf") await window.QCMSave.remindProjectSave();
  return response;
}

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value !== undefined && value !== null) node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

const fmt = (value) => Number(value).toFixed(1);

// ---------------------------------------------------------------------------
// Onglets
// ---------------------------------------------------------------------------
const tabListeners = {};
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("section.tab").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  (tabListeners[name] || []).forEach((listener) => listener());
}
function onTab(name, listener) { (tabListeners[name] ||= []).push(listener); }
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------------------
// Projet : état partagé
// ---------------------------------------------------------------------------
let project = null;
let selected = null; // { e } ou { e, q }

function applyProject(data) {
  project = data;
  $("#project-name").textContent = data.name || data.settings.evaluation_short || "Projet non enregistré";
  $("#btn-save").hidden = false;
  fillForm($("#info-form"), data.settings);
  fillForm($("#gen-form"), data.settings);
  renderTree();
}

function fillForm(form, settings) {
  for (const field of form.elements) {
    if (!field.name || !(field.name in settings) || field === document.activeElement) continue;
    if (field.type === "checkbox") field.checked = Boolean(settings[field.name]);
    else field.value = settings[field.name] ?? "";
  }
}

function fieldValue(field) {
  if (field.type === "checkbox") return field.checked;
  if (field.type === "number") return Number(field.value);
  return field.value;
}

function bindSettingsForm(form) {
  form.addEventListener("change", (event) => {
    const field = event.target;
    if (!field.name) return;
    guard(async () => applyProject(await api("PUT", "/api/settings", { [field.name]: fieldValue(field) })));
  });
}

// ---------------------------------------------------------------------------
// Fichier
// ---------------------------------------------------------------------------
$("#btn-new").addEventListener("click", () => guard(async () => {
  if (!(await window.QCMSave.beforeReplace())) return;
  selected = null;
  applyProject(await api("POST", "/api/project/new"));
  await window.QCMSave.resetPath();
  $("#file-status").textContent = "Projet nouveau (non enregistré).";
  document.dispatchEvent(new CustomEvent("project-reset"));
}));
$("#btn-open").addEventListener("click", () => guard(() => window.QCMSave.openProject()));
$("#input-project").addEventListener("change", (event) => guard(async () => {
  const file = event.target.files[0];
  if (!file) return;
  if (!(await window.QCMSave.beforeReplace())) { event.target.value = ""; return; }
  const body = new FormData();
  body.append("file", file);
  selected = null;
  applyProject(await api("POST", "/api/project/open", body));
  await window.QCMSave.resetPath();
  document.dispatchEvent(new CustomEvent("project-reset"));
  $("#file-status").textContent = `Projet chargé : ${file.name}`;
  event.target.value = "";
}));
$("#btn-save").addEventListener("click", () => guard(() => window.QCMSave.saveProject(false)));
$("#btn-save-as").addEventListener("click", () => guard(() => window.QCMSave.saveProject(true)));
$("#btn-download").addEventListener("click", () => guard(() => window.QCMSave.saveProject(true)));

// ---------------------------------------------------------------------------
// Structure
// ---------------------------------------------------------------------------
const QUESTION_TYPES = [
  ["single", "Choix unique"],
  ["multiple_exact", "Choix multiples à correspondance exacte (toute erreur ou omission entraîne le malus)"],
  ["multiple_progressive", "Choix multiples à gain progressif (gain dégressif selon les omissions, toute erreur entraîne le malus)"],
  ["manual", "Correction manuelle (réponse libre)"],
];
const CHOICE_STATES = [["correct", "Correct"], ["neutral", "Neutre"], ["penalty", "Faux"]];

// Boutons « monter », « descendre » et « supprimer » d'une ligne de l'arbre.
// Les mêmes règles que l'éditeur GTK s'appliquent : un projet garde au moins un
// exercice, un exercice au moins une question.
function rowActions({ label, count, index, disabledRemove, move, remove }) {
  const button = (text, title, onclick, disabled, className = "") =>
    el("button", {
      type: "button", class: className, title, "aria-label": title, disabled,
      onclick: (ev) => { ev.stopPropagation(); guard(onclick); },
    }, text);
  return el("span", { class: "row-actions" },
    button("▲", `Monter ${label}`, () => move(-1), index === 0),
    button("▼", `Descendre ${label}`, () => move(+1), index === count - 1),
    button("✕", `Supprimer ${label}`, remove, disabledRemove, "remove"),
  );
}

function renderTree() {
  const { structure } = project;
  $("#interval").textContent = `Intervalle : ${fmt(structure.range[0])} ↗ ${fmt(structure.range[1])}`;
  const tree = $("#tree");
  tree.replaceChildren();
  const exercises = structure.exercises;
  exercises.forEach((exercise, e) => {
    const exUrl = `/api/structure/exercises/${e}`;
    const item = el("li", { class: "exercise", tabindex: "0", onclick: () => select({ e }) },
      el("span", { class: "label" },
        `Exercice ${e + 1} : ${exercise.name} ${fmt(exercise.range[0])} ↗ ${fmt(exercise.range[1])}`),
      rowActions({
        label: `l'exercice ${e + 1}`, count: exercises.length, index: e,
        disabledRemove: exercises.length <= 1,
        move: (delta) => moveItem(exUrl, { e }, delta),
        remove: () => removeItem(exUrl, `Supprimer « ${exercise.name} » et toutes ses questions ?`, { e }),
      }));
    item.classList.toggle("selected", Boolean(selected && selected.e === e && selected.q === undefined));
    tree.append(item);
    exercise.questions.forEach((question, q) => {
      const qUrl = `${exUrl}/questions/${q}`;
      const row = el("li", { class: "question", tabindex: "0", onclick: () => select({ e, q }) },
        el("span", { class: "label" },
          `Q${q + 1} : ${question.name} ${question.range[0]} ↗ ${question.range[1]} `,
          ...question.choices.map((c) => el("span", { class: `choice ${c.state}` }, `(${c.name})`))),
        rowActions({
          label: `la question ${q + 1}`, count: exercise.questions.length, index: q,
          disabledRemove: exercise.questions.length <= 1,
          move: (delta) => moveItem(qUrl, { e, q }, delta),
          remove: () => removeItem(qUrl, `Supprimer « ${question.name} » ?`, { e, q }),
        }));
      row.classList.toggle("selected", Boolean(selected && selected.e === e && selected.q === q));
      tree.append(row);
    });
  });
  renderProps();
}

// Déplacement d'un cran : la sélection suit l'élément déplacé.
async function moveItem(url, target, delta) {
  const data = await structureCall("POST", `${url}/move`, { delta });
  if (!data.accepted) return;
  selected = target.q === undefined
    ? { e: target.e + delta }
    : { e: target.e, q: target.q + delta };
  renderTree();
}

// Suppression après confirmation, comme le dialogue de l'éditeur GTK.
async function removeItem(url, message, target) {
  if (!(await confirmRemoval(message))) return;
  const data = await structureCall("DELETE", url);
  if (!data.accepted) {
    toast(target.q === undefined
      ? "Le projet doit garder au moins un exercice."
      : "Un exercice doit garder au moins une question.", true);
    return;
  }
  const exercises = data.structure.exercises;
  if (target.q === undefined) {
    selected = exercises.length ? { e: Math.min(target.e, exercises.length - 1) } : null;
  } else {
    const questions = exercises[target.e].questions;
    selected = { e: target.e, q: Math.min(target.q, questions.length - 1) };
  }
  renderTree();
}

// Confirmation par <dialog> : pas de window.confirm, qui bloque la fenêtre.
function confirmRemoval(message) {
  const dialog = $("#dlg-confirm");
  $("#confirm-title").textContent = "Suppression définitive";
  $("#confirm-message").textContent = `${message} Cette action est irréversible.`;
  return new Promise((resolve) => {
    // Le gestionnaire est retiré avant la fermeture : sans cela, close()
    // déclencherait « onclose » et la promesse se résoudrait toujours à false.
    const close = (value) => { dialog.onclose = null; dialog.close(); resolve(value); };
    dialog.onclose = () => resolve(false);  // Fermeture par Échap.
    $("#confirm-ok").onclick = () => close(true);
    $("#confirm-cancel").onclick = () => close(false);
    dialog.showModal();
    $("#confirm-cancel").focus();
  });
}

function select(target) {
  selected = target;
  renderTree();
}

async function structureCall(method, url, body) {
  const data = await api(method, url, body);
  applyProject(data);
  return data;
}

function numberInput(value, onChange) {
  return el("input", { type: "number", min: "0", max: "1000", step: "0.5", value, onchange: (ev) => onChange(Number(ev.target.value)) });
}

function textInput(value, onChange) {
  return el("input", { value, onchange: (ev) => onChange(ev.target.value) });
}

function renderProps() {
  const panel = $("#props");
  panel.replaceChildren();
  const exercise = selected && project.structure.exercises[selected.e];
  if (!exercise) {
    panel.append(el("p", { class: "muted" }, "Sélectionnez un exercice ou une question."));
    return;
  }
  const exUrl = `/api/structure/exercises/${selected.e}`;
  if (selected.q === undefined) {
    const patch = (data) => guard(() => structureCall("PATCH", exUrl, data));
    panel.append(
      el("h2", {}, "Exercice"),
      el("label", {}, "Nom", textInput(exercise.name, (v) => patch({ name: v }))),
      el("label", {}, "Introduction", textInput(exercise.header, (v) => patch({ header: v }))),
      el("div", { class: "row" }, el("button", { onclick: () => guard(() => structureCall("POST", `${exUrl}/questions`)) }, "Ajouter une question")),
      el("label", { class: "check" },
        el("input", { type: "checkbox", checked: exercise.validation, onchange: (ev) => patch({ validation: ev.target.checked }) }),
        "Validation par seuil"),
      el("div", { class: "row wrap" },
        el("label", {}, "Gain si validité", numberInput(exercise.gain, (v) => patch({ gain: v }))),
        el("label", {}, "Seuil", numberInput(exercise.threshold, (v) => patch({ threshold: v })))),
      el("label", { class: "check" },
        el("input", { type: "checkbox", checked: exercise.min0, onchange: (ev) => patch({ min0: ev.target.checked }) }),
        "Note minimale 0 (pas de points négatifs)"),
    );
    return;
  }
  const question = exercise.questions[selected.q];
  if (!question) return;
  const qUrl = `${exUrl}/questions/${selected.q}`;
  const patch = (data) => guard(() => structureCall("PATCH", qUrl, data));
  const typeSelect = el("select", { onchange: (ev) => patch({ type: ev.target.value }) },
    ...QUESTION_TYPES.map(([value, label]) => el("option", { value, selected: value === question.type }, label)));
  const states = el("div", { class: "choice-states" });
  question.choices.forEach((choice, c) => {
    const stateSelect = el("select", {
      "aria-label": `État du choix ${choice.name}`,
      onchange: (ev) => guard(async () => {
        const data = await structureCall("PUT", `${qUrl}/choices/${c}`, { state: ev.target.value });
        if (!data.accepted) toast("En choix unique, il faut garder un choix correct.", true);
      }),
    }, ...CHOICE_STATES.map(([value, label]) => el("option", { value, selected: value === choice.state }, label)));
    states.append(el("span", { class: `choice ${choice.state}` }, `${choice.name})`), stateSelect);
  });
  panel.append(
    el("h2", {}, "Question"),
    el("label", {}, "Nom", textInput(question.name, (v) => patch({ name: v }))),
    el("div", { class: "row wrap" },
      el("label", {}, "Gain", numberInput(question.gain, (v) => patch({ gain: v }))),
      el("label", {}, question.type === "multiple_progressive" ? "Malus par réponse fausse" : "Malus de la question", numberInput(question.penalty, (v) => patch({ penalty: v }))),
      el("button", { onclick: () => guard(() => structureCall("POST", `${qUrl}/choices`)) }, "Ajouter un choix"),
      el("button", { onclick: () => guard(() => structureCall("DELETE", `${qUrl}/choices`)) }, "Enlever un choix")),
    el("label", {}, "Type de question", typeSelect),
    el("h2", {}, "Choix"),
    states,
  );
}

$("#btn-add-exercise").addEventListener("click", () => guard(async () => {
  const data = await structureCall("POST", "/api/structure/exercises");
  select({ e: data.structure.exercises.length - 1 });
}));

// ---------------------------------------------------------------------------
// Génération
// ---------------------------------------------------------------------------
const DIR_OPTIONS = [["left", "→ puis ↓"], ["top", "↓ puis →"], ["both", "Aléatoire"]];
const TRI_OPTIONS = [["never", "Jamais"], ["always", "Toujours"], ["sometimes", "De temps en temps"]];

function selectField(label, name, options) {
  return el("label", {}, label, el("select", { name }, ...options.map(([value, text]) => el("option", { value }, text))));
}
function countField(label, name) {
  return el("label", {}, label, el("input", { name, type: "number", min: "1", max: "9" }));
}
function nameField(label, name) {
  return el("label", {}, label, el("input", { name }));
}

$("#dir-fields").append(
  selectField("Identification", "identification_dir", DIR_OPTIONS),
  selectField("Exercices", "exercise_dir", DIR_OPTIONS),
  selectField("Questions", "question_dir", DIR_OPTIONS),
  selectField("Choix", "choice_dir", DIR_OPTIONS),
);
$("#order-fields").append(
  selectField("Ordre des exercices", "exercise_order", TRI_OPTIONS),
  selectField("Ordre des questions", "question_order", TRI_OPTIONS),
  selectField("Ordre des choix", "choice_order", TRI_OPTIONS),
);
$("#phantom-fields").append(
  selectField("Exercices fantômes", "exercise_new", TRI_OPTIONS),
  countField("Nombre d'exercices", "exercise_new_exercises"),
  nameField("Intitulé des exercices", "exercise_new_exercises_name"),
  countField("Questions par exercice", "exercise_new_questions"),
  nameField("Intitulé des questions", "exercise_new_questions_name"),
  countField("Choix par question", "exercise_new_choices"),
  nameField("Intitulé des choix", "exercise_new_choices_name"),
  selectField("Questions fantômes", "question_new", TRI_OPTIONS),
  countField("Nombre de questions", "question_new_questions"),
  nameField("Intitulé des questions", "question_new_questions_name"),
  countField("Choix par question", "question_new_choices"),
  nameField("Intitulé des choix", "question_new_choices_name"),
  selectField("Choix fantômes", "choice_new", TRI_OPTIONS),
  countField("Nombre de choix", "choice_new_choices"),
  nameField("Intitulé des choix", "choice_new_choices_name"),
  selectField("Choix fantômes précochés", "choice_checked", TRI_OPTIONS),
);

$("#btn-gen-variants").addEventListener("click", () => guard(async () => {
  $("#generate-status").textContent = "Génération…";
  await window.QCMSave.settle();
  const data = await api("POST", "/api/generate/variants");
  applyProject(data);
  $("#generate-status").textContent = data.message;
}));
$("#btn-gen-bundle").addEventListener("click", () => guard(() => download("/api/generate/bundle", "sujet_et_projet.zip")));
$("#btn-gen-pdf").addEventListener("click", () => guard(async () => {
  $("#generate-status").textContent = "Création du PDF…";
  await download("/api/generate/pdf", "sujet.pdf");
}));

// ---------------------------------------------------------------------------
// Aide
// ---------------------------------------------------------------------------
onTab("help", () => guard(async () => {
  if ($("#help-text").childElementCount) return;
  const response = await api("GET", "/api/help");
  $("#help-text").innerHTML = window.QCMMarkdown.render(await response.text());
}));

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------
bindSettingsForm($("#info-form"));
bindSettingsForm($("#gen-form"));
window.QCM = { $, api, guard, toast, download, el, onTab, showTab, applyProject, get project() { return project; } };
guard(async () => applyProject(await api("GET", "/api/project")));
