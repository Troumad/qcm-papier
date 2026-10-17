"use strict";
// Onglet Correction : notation des questions à réponse libre, question par
// question sur toutes les copies, avec l'aide à la correction (repliable).

(() => {
  const { $, api, guard, toast, el, onTab } = window.QCM;
  const HELP_KEY = "qcm-manual-help";

  let questions = [];
  let current = null; // "e:q" de la question affichée

  const key = (question) => `${question.e}:${question.q}`;
  const points = (value) => Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 2 });

  function readHelpPreference() {
    try { return localStorage.getItem(HELP_KEY) !== "hidden"; } catch { return true; }
  }

  function setHelpVisible(visible) {
    $("#manual-help-toggle").checked = visible;
    $("#manual-help").hidden = !visible;
    try { localStorage.setItem(HELP_KEY, visible ? "shown" : "hidden"); } catch { /* stockage indisponible */ }
  }

  async function refresh() {
    const data = await api("GET", "/api/manual");
    questions = data.questions;
    const section = $("#manual-grading");
    section.hidden = !questions.some((question) => question.rows.length);
    if (section.hidden) return;
    if (!questions.some((question) => key(question) === current)) {
      current = key(questions.find((question) => question.remaining) || questions[0]);
    }
    $("#manual-question").replaceChildren(...questions.map((question) => el("option", {
      value: key(question), selected: key(question) === current,
    }, `${question.exercise} — ${question.name} (${question.remaining} à noter)`)));
    render();
  }

  function selected() {
    return questions.find((question) => key(question) === current);
  }

  function renderProgress(question) {
    const done = question.rows.length - question.remaining;
    $("#manual-progress").textContent = `${done}/${question.rows.length} notée(s), sur ${points(question.gain)} pt`;
    const option = $(`#manual-question option[value="${current}"]`);
    if (option) option.textContent = `${question.exercise} — ${question.name} (${question.remaining} à noter)`;
  }

  function renderHelp(question) {
    const markdown = (text) => (text ? window.QCMMarkdown.render(text) : '<p class="muted">Non renseigné (onglet Structure).</p>');
    $("#manual-expected").innerHTML = markdown(question.expected);
    $("#manual-notes").innerHTML = markdown(question.grading_notes);
  }

  function render() {
    const question = selected();
    if (!question) return;
    renderHelp(question);
    renderProgress(question);
    const onlyTodo = $("#manual-todo").checked;
    const rows = question.rows.filter((row) => !onlyTodo || row.value === null);
    const list = $("#manual-rows");
    list.replaceChildren(...rows.map((row) => renderRow(question, row)));
    if (!rows.length) list.append(el("li", { class: "muted" }, "Toutes les réponses sont notées."));
  }

  function renderRow(question, row) {
    const url = `/api/pages/${row.index}/manual/${question.e}/${question.q}`;
    const input = el("input", {
      type: "number", min: "0", max: String(question.gain), step: "0.25",
      value: row.value ?? "", "aria-label": `Points de ${row.student || row.file}`,
    });
    const item = el("li", { class: row.value === null ? "todo" : "" });

    async function save(value) {
      await guard(async () => {
        await api("PUT", url, { value });
        row.value = value;
        question.remaining = question.rows.filter((r) => r.value === null).length;
        input.value = value ?? "";
        item.classList.toggle("todo", value === null);
        renderProgress(question);
        document.dispatchEvent(new CustomEvent("qcm:correction-changed"));
      });
    }

    function next() {
      const inputs = [...$("#manual-rows").querySelectorAll("input")];
      const following = inputs[inputs.indexOf(input) + 1];
      if (following) { following.focus(); following.select(); }
    }

    input.addEventListener("change", () => {
      const text = input.value.trim();
      if (text === "") return save(null);
      const value = Number(text);
      if (!(value >= 0 && value <= question.gain)) {
        toast(`Les points doivent être compris entre 0 et ${points(question.gain)}.`, true);
        input.value = row.value ?? "";
        return undefined;
      }
      return save(value);
    });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); input.dispatchEvent(new Event("change")); next(); }
    });

    const quick = (value, label) => el("button", {
      type: "button", "aria-label": `${label} pour ${row.student || row.file}`,
      onclick: async () => { await save(value); next(); },
    }, label);
    item.append(
      el("div", { class: "manual-who" },
        el("strong", {}, row.student || "Étudiant non identifié"),
        el("span", { class: "muted" }, row.file)),
      el("img", {
        src: `${url}/image`, loading: "lazy", class: "manual-answer",
        alt: `Réponse de ${row.student || row.file} à ${question.name}`,
      }),
      el("div", { class: "manual-points" },
        el("div", { class: "row" }, quick(0, "0"), quick(question.gain / 2, "½"), quick(question.gain, points(question.gain))),
        el("label", {}, "Points", input),
        el("button", { type: "button", class: "link", onclick: () => save(null) }, "Effacer")),
    );
    return item;
  }

  $("#manual-question").addEventListener("change", (ev) => { current = ev.target.value; render(); });
  $("#manual-todo").addEventListener("change", render);
  $("#manual-help-toggle").addEventListener("change", (ev) => setHelpVisible(ev.target.checked));
  setHelpVisible(readHelpPreference());

  onTab("correct", () => guard(refresh));
  document.addEventListener("qcm:correction-refreshed", () => guard(refresh));
  window.QCMManual = { refresh };
})();
