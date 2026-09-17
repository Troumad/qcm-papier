const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");

async function harness({ dirty = true, target = "/tmp/projet.json", fail = false } = {}) {
  const nodes = new Map();
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, { listeners: {}, addEventListener(n, cb) { this.listeners[n] = cb; },
      showModal() { this.open = true; }, close() { this.open = false; }, focus() {} });
    return nodes.get(selector);
  };
  const work = { project_dirty: dirty, correction_dirty: false, running: false };
  const calls = [];
  const events = {};
  let boot;
  const window = { __TAURI__: { core: { async invoke(command) {
    calls.push(command);
    if (command === "save_document") { if (fail) throw new Error("Disque plein"); return target; }
  } } }, addEventListener(name, cb) { events[name] = cb; } };
  window.QCM = { $: node, toast() {}, guard(action) { boot = action(); }, async api(method, url, body) {
    if (url === "/api/work/saved") { calls.push(body); work.project_dirty = false; }
    if (url === "/api/project/download") return response();
    return { ...work };
  } };
  vm.runInNewContext(fs.readFileSync("qcm_papier/web/static/persistence.js", "utf8"), {
    window, document: { activeElement: null, addEventListener() {} }, setTimeout, URL, Uint8Array,
  });
  await boot;
  return { save: window.QCMSave, calls, node, events, work };
}
function response() {
  return { headers: new Headers([["X-Project-Token", "snapshot"]]),
    async blob() { return { async arrayBuffer() { return new Uint8Array([123, 125]).buffer; } }; } };
}
test("annuler le dialogue natif ne valide pas la sauvegarde", async () => {
  const h = await harness({ target: null });
  assert.equal(await h.save.deliver(response(), "projet.json", { project: true }), false);
  assert.equal(h.work.project_dirty, true);
  assert.ok(!h.calls.some((c) => typeof c === "object"));
});
test("une erreur d’écriture conserve le travail non enregistré", async () => {
  const h = await harness({ fail: true });
  await assert.rejects(h.save.deliver(response(), "projet.json"), /Disque plein/);
  assert.equal(h.work.project_dirty, true);
});
test("une écriture réussie valide uniquement le jeton du document téléchargé", async () => {
  const h = await harness();
  assert.equal(await h.save.deliver(response(), "projet.json"), true);
  const acknowledgement = h.calls.find((c) => typeof c === "object");
  assert.equal(acknowledgement.project_token, "snapshot");
  assert.equal(acknowledgement.correction_token, null);
});
test("annuler le remplacement conserve le projet", async () => {
  const h = await harness();
  const decision = h.save.beforeReplace();
  await new Promise(setImmediate);
  assert.equal(h.node("#dlg-unsaved").open, true);
  h.node("#unsaved-cancel").onclick();
  assert.equal(await decision, false);
  assert.equal(h.work.project_dirty, true);
});
test("une correction en cours interdit le remplacement", async () => {
  const h = await harness({ dirty: false });
  h.work.running = true;
  assert.equal(await h.save.beforeReplace(), false);
});
test("une saisie récente reste protégée quand une requête antérieure termine", async () => {
  const h = await harness({ dirty: false });
  const version = h.save.beginMutation();
  h.node("#props").listeners.input();
  await h.save.endMutation(true, version);
  let prevented = false;
  h.events.beforeunload({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
});

test("le PDF propose de conserver le JSON et laisse un rappel si on reporte", async () => {
  const h = await harness();
  const reminder = h.save.remindProjectSave();
  assert.equal(h.node("#dlg-pdf-json").open, true);
  h.node("#pdf-json-later").onclick();
  await reminder;
  assert.match(h.node("#generate-status").textContent, /indispensable/);
  assert.equal(h.work.project_dirty, true);
});
test("le rappel PDF permet d'enregistrer le JSON", async () => {
  const h = await harness();
  const reminder = h.save.remindProjectSave();
  h.node("#pdf-json-save").onclick();
  await reminder;
  assert.ok(h.calls.includes("save_document"));
  assert.equal(h.work.project_dirty, false);
});
test("annuler la sauvegarde JSON après le PDF conserve le rappel", async () => {
  const h = await harness({ target: null });
  const reminder = h.save.remindProjectSave();
  h.node("#pdf-json-save").onclick();
  await reminder;
  assert.match(h.node("#generate-status").textContent, /indispensable/);
  assert.equal(h.work.project_dirty, true);
});
